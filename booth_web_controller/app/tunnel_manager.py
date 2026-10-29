"""Cloudflare Quick Tunnel Manager and Workers KV Auto-Updater.

Runs as an async task within FastAPI lifespan when ENABLE_TUNNEL=true.
Completely isolated from the ROS agent process manager.
"""

import asyncio
from dataclasses import dataclass
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse
import urllib.request
import urllib.error


# Hostname regex strictly matching *.trycloudflare.com (excluding apex)
TRYCLOUDFLARE_REGEX = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*\.trycloudflare\.com$",
    re.IGNORECASE,
)

# Pattern to search for tunnel URLs in cloudflared logs
TUNNEL_URL_PATTERN = re.compile(r"https://[a-zA-Z0-9.-]+\.trycloudflare\.com(?![a-zA-Z0-9.-])", re.IGNORECASE)

try:
    BOOT_ID = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
except Exception:
    BOOT_ID = "unknown-boot"


def get_process_identity(pid: int) -> Optional[str]:
    """Return a unique process identity based on boot ID and process start ticks."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if stat[0] == "Z":  # Zombie process
            return None
        return f"{BOOT_ID}:{stat[19]}"
    except (OSError, IndexError):
        return None


def validate_trycloudflare_url(url_str: Optional[str]) -> Optional[str]:
    """Validates that a URL is a safe, valid trycloudflare.com tunnel URL.

    Requirements:
    - Scheme must be https
    - Hostname must be a valid subdomain of trycloudflare.com (not apex)
    - No custom port, query, fragment, userinfo, or non-root path
    """
    if not isinstance(url_str, str) or not url_str.strip():
        return None

    trimmed = url_str.strip()
    try:
        parsed = urlparse(trimmed)
    except Exception:
        return None

    if parsed.scheme.lower() != "https":
        return None

    if parsed.username or parsed.password:
        return None

    try:
        if parsed.port is not None and parsed.port != 443:
            return None
    except ValueError:
        return None

    if parsed.query or parsed.fragment:
        return None

    # Path must be empty or '/'
    if parsed.path not in ("", "/"):
        return None

    hostname = (parsed.hostname or "").lower()
    if not hostname or hostname == "trycloudflare.com":
        return None

    if not TRYCLOUDFLARE_REGEX.match(hostname):
        return None

    return f"https://{hostname}/"


def parse_tunnel_url_from_output(text: str) -> Optional[str]:
    """Finds the first valid trycloudflare.com URL in stdout/stderr text."""
    if not text:
        return None
    for match in TUNNEL_URL_PATTERN.finditer(text):
        candidate = match.group(0)
        valid = validate_trycloudflare_url(candidate)
        if valid:
            return valid
    return None


@dataclass
class TunnelSnapshot:
    enabled: bool
    running: bool
    pid: Optional[int]
    tunnel_url: Optional[str]
    worker_static_url: Optional[str]
    target_reachable: bool
    target_probed_at: Optional[float]
    kv_update_accepted: bool
    kv_written_at: Optional[float]
    last_error: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "enabled": self.enabled,
            "running": self.running,
            "pid": self.pid,
            "tunnel_url": self.tunnel_url,
            "worker_static_url": self.worker_static_url,
            "target_reachable": self.target_reachable,
            "target_probed_at": self.target_probed_at,
            "kv_update_accepted": self.kv_update_accepted,
            "kv_written_at": self.kv_written_at,
            "last_error": self.last_error,
        }


class TunnelManager:
    """Manages cloudflared Quick Tunnel process, readiness probe, and Cloudflare KV updates."""

    def __init__(
        self,
        *,
        enabled: bool = False,
        port: int = 8000,
        instance_id: str = "",
        worker_static_url: str = "",
        cf_api_token: str = "",
        cf_account_id: str = "",
        cf_namespace_id: str = "",
        cf_key: str = "robot_url",
        probe_interval_sec: float = 15.0,
        cloudflared_bin: str = "cloudflared",
        local_url: str = "",
        http_request=None,
        sleep=asyncio.sleep,
    ):
        self.enabled = bool(enabled)
        self.port = port
        self.instance_id = instance_id
        self.worker_static_url = worker_static_url.strip()
        self.cf_api_token = cf_api_token.strip()
        self.cf_account_id = cf_account_id.strip()
        self.cf_namespace_id = cf_namespace_id.strip()
        self.cf_key = cf_key.strip() or "robot_url"
        self.probe_interval_sec = max(3.0, float(probe_interval_sec))
        self.cloudflared_bin = cloudflared_bin
        self.local_url = local_url
        self._http_request = http_request or self._request
        self._uses_default_http = http_request is None
        self._sleep = sleep

        # Runtime process ownership
        self.process: Optional[asyncio.subprocess.Process] = None
        self.pid: Optional[int] = None
        self.start_ticks: Optional[str] = None
        self._lock_file: Optional[Path] = None
        self._lock_fd: Optional[int] = None

        # State tracking
        self.current_tunnel_url: Optional[str] = None
        self.target_reachable: bool = False
        self.last_probed_at: Optional[float] = None
        self.kv_update_accepted: bool = False
        self.last_kv_written_at: Optional[float] = None
        self.last_error: Optional[str] = None
        self._last_error_source: Optional[str] = None

        # Background tasks
        self._monitor_task: Optional[asyncio.Task] = None
        self._probe_task: Optional[asyncio.Task] = None
        self._stopped = False

    @staticmethod
    def _request(url: str, *, method: str = "GET", token: str = "", data: bytes = b"", timeout: float = 5.0):
        headers = {"User-Agent": "TurtleBot-TunnelProbe/1.0"}
        if token:
            headers.update({"Authorization": f"Bearer {token}", "Content-Type": "text/plain; charset=utf-8"})
        req = urllib.request.Request(url, data=data if method == "PUT" else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return resp.status, body
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")

    async def _request_async(self, url: str, **kwargs):
        if self._uses_default_http:
            return await asyncio.wait_for(asyncio.to_thread(self._http_request, url, **kwargs),
                                          timeout=kwargs.get("timeout", 5.0) + 0.5)
        result = self._http_request(url, **kwargs)
        if asyncio.iscoroutine(result):
            return await asyncio.wait_for(result, timeout=kwargs.get("timeout", 5.0) + 0.5)
        return result

    def sanitize_error(self, message: Optional[str]) -> Optional[str]:
        """Strip sensitive credentials from error messages."""
        if not message:
            return None
        text = str(message)
        if self.cf_api_token and len(self.cf_api_token) > 4:
            text = text.replace(self.cf_api_token, "[REDACTED_API_TOKEN]")
        text = re.sub(r"(?i)(authorization\s*[:=]\s*bearer\s+)\S+", r"\1[REDACTED]", text)
        text = re.sub(r"(?i)(api[_-]?token\s*[:=]\s*)\S+", r"\1[REDACTED]", text)
        return text

    def is_process_running(self) -> bool:
        """Verify that the tracked cloudflared process is still alive and owned."""
        if self.process is None or self.pid is None or self.start_ticks is None:
            return False
        if self.process.returncode is not None:
            return False
        current_identity = get_process_identity(self.pid)
        return current_identity == self.start_ticks

    def _acquire_lock(self) -> bool:
        """Acquire a machine-local single-instance file lock for this account/namespace/key."""
        key_digest = hashlib.sha256(
            f"{self.cf_account_id}:{self.cf_namespace_id}:{self.cf_key}".encode()
        ).hexdigest()[:16]
        state_dir = Path.home() / ".local/state/turtlebot-tunnel"
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock_file = state_dir / f"tunnel_{key_digest}.lock"

        try:
            self._lock_fd = os.open(
                self._lock_file, os.O_CREAT | os.O_RDWR, 0o600
            )
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError) as exc:
            self.last_error = (
                f"Another tunnel manager instance is already active for this KV namespace ({exc})"
            )
            if self._lock_fd is not None:
                try:
                    os.close(self._lock_fd)
                except OSError:
                    pass
                self._lock_fd = None
            return False

    def _release_lock(self) -> None:
        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
                os.close(self._lock_fd)
            except OSError:
                pass
            self._lock_fd = None

    def _api_url(self) -> str:
        from urllib.parse import quote
        return (f"https://api.cloudflare.com/client/v4/accounts/{quote(self.cf_account_id, safe='')}"
                f"/storage/kv/namespaces/{quote(self.cf_namespace_id, safe='')}"
                f"/values/{quote(self.cf_key, safe='')}")

    async def start(self) -> None:
        """Starts the tunnel manager if enabled."""
        if not self.enabled:
            return

        self._stopped = False

        # 1. Acquire single-instance lock
        if not self._acquire_lock():
            return

        # 2. Check cloudflared binary
        resolved_bin = shutil.which(self.cloudflared_bin)
        if not resolved_bin:
            self.last_error = "cloudflared could not be started; check that it is installed and executable"
            self._last_error_source = "process"
            self._release_lock()
            return

        # 3. Launch cloudflared process
        cmd = [
            resolved_bin,
            "tunnel",
            "--url",
            f"http://127.0.0.1:{self.port}",
            "--no-autoupdate",
        ]

        try:
            self.process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                preexec_fn=os.setsid,  # Create new process group
            )
            self.pid = self.process.pid
            self.start_ticks = get_process_identity(self.pid)
        except Exception as exc:
            self.last_error = f"Failed to start cloudflared ({type(exc).__name__})"
            self._last_error_source = "process"
            self._release_lock()
            return

        if self.start_ticks is None:
            self.last_error = "Could not verify ownership of the cloudflared process"
            self._last_error_source = "process"
            await self.stop()
            return

        # 4. Start background log reader & monitor tasks
        self._monitor_task = asyncio.create_task(self._read_tunnel_output())
        self._probe_task = asyncio.create_task(self._probe_and_update_loop())

    async def _read_tunnel_output(self) -> None:
        """Reads cloudflared logs line-by-line to extract the active Quick Tunnel URL."""
        if not self.process or not self.process.stdout:
            return

        while not self._stopped and self.process.returncode is None:
            try:
                line = await self.process.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="replace")
                if not self.current_tunnel_url:
                    parsed = parse_tunnel_url_from_output(text)
                    if parsed:
                        self.current_tunnel_url = parsed
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.last_error = self.sanitize_error(f"Error reading tunnel output: {type(exc).__name__}")
                break

    async def _probe_and_update_loop(self) -> None:
        """Periodically tests public URL reachability and writes to KV."""
        # Initial grace period: wait for tunnel URL to be detected
        for _ in range(30):
            if self._stopped or self.current_tunnel_url:
                break
            await asyncio.sleep(0.5)

        last_written_target: Optional[str] = await self._read_existing_kv()
        write_attempted_for_url: Optional[str] = None
        if last_written_target == self.current_tunnel_url:
            self.kv_update_accepted = True

        while not self._stopped:
            try:
                if not self.is_process_running():
                    self.target_reachable = False
                    if self._last_error_source != "kv":
                        self.last_error = "cloudflared process terminated unexpectedly"
                        self._last_error_source = "process"
                    await self._sleep(2.0)
                    continue

                if not self.current_tunnel_url:
                    await self._sleep(1.0)
                    continue

                # Run readiness probe
                reachable = await self._probe_health(self.current_tunnel_url)
                self.last_probed_at = time.time()
                self.target_reachable = reachable

                if reachable:
                    # Attempt a URL once per manager lifetime, even after a bounded failure.
                    if (last_written_target != self.current_tunnel_url
                            and write_attempted_for_url != self.current_tunnel_url):
                        write_attempted_for_url = self.current_tunnel_url
                        success = await self._write_kv_with_retry(self.current_tunnel_url)
                        if success:
                            last_written_target = self.current_tunnel_url
                else:
                    if self._last_error_source != "kv":
                        self.last_error = (
                            f"Health probe to public tunnel {self.current_tunnel_url} failed"
                        )
                        self._last_error_source = "probe"

                if reachable and self._last_error_source == "probe":
                    self.last_error = None
                    self._last_error_source = None

                await self._sleep(self.probe_interval_sec)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                self.last_error = self.sanitize_error(f"Unexpected probe loop error: {exc}")
                self._last_error_source = "manager"
                await self._sleep(self.probe_interval_sec)

    async def _probe_health(self, tunnel_url: str) -> bool:
        """Probes the /api/v1/health endpoint on both localhost and public tunnel.

        Verifies that:
        1. Both return HTTP 200
        2. Both return matching instance_id (guarantees public tunnel reaches THIS server)
        """
        normalized = validate_trycloudflare_url(tunnel_url)
        if normalized is None:
            return False
        for url, timeout in ((f"http://127.0.0.1:{self.port}/api/v1/health", 3.0),
                             (normalized.rstrip("/") + "/api/v1/health", 5.0)):
            try:
                status, body = await self._request_async(url, timeout=timeout)
                data = json.loads(body)
                if status != 200 or data.get("service") != "mobile-web-voice-text-controller" or data.get("instance_id") != self.instance_id:
                    return False
            except Exception:
                return False
        return True

    async def _read_existing_kv(self) -> Optional[str]:
        if not all((self.cf_api_token, self.cf_account_id, self.cf_namespace_id)):
            return None
        url = self._api_url()
        try:
            status, body = await self._request_async(url, token=self.cf_api_token)
            if status == 200:
                return validate_trycloudflare_url(body)
        except Exception:
            pass
        return None

    async def _write_kv_with_retry(self, target_url: str) -> bool:
        """Writes the active tunnel URL to Cloudflare Workers KV with bounded retry and backoff.

        Rules:
        - Max 3 attempts total (initial attempt + up to 2 retries)
        - Delays: 2s, 4s
        - Stop immediately on HTTP 401 or 403 (do not retry)
        - Verify HTTP status 200 AND JSON success: true
        """
        if not self.cf_api_token or not self.cf_account_id or not self.cf_namespace_id:
            self.last_error = (
                "Cloudflare KV configuration missing: CLOUDFLARE_API_TOKEN, "
                "CLOUDFLARE_ACCOUNT_ID, and CLOUDFLARE_KV_NAMESPACE_ID must be set"
            )
            return False

        api_url = self._api_url()

        delays = [2.0, 4.0]
        max_attempts = 3

        for attempt in range(max_attempts):
            if self._stopped:
                return False

            try:
                status, response_text = await self._request_async(
                    api_url, method="PUT", token=self.cf_api_token,
                    data=target_url.encode("utf-8"), timeout=5.0)
                success = bool(json.loads(response_text).get("success", False))
            except Exception as exc:
                status, success, response_text = 0, False, type(exc).__name__

            if status == 200 and success:
                self.kv_update_accepted = True
                self.last_kv_written_at = time.time()
                self.last_error = None
                self._last_error_source = None
                return True

            # Stop immediately without retrying on authentication/authorization errors
            if status in (401, 403):
                self.last_error = (
                    f"Cloudflare KV update rejected with HTTP {status}: invalid API token or insufficient permissions"
                )
                self._last_error_source = "kv"
                self.kv_update_accepted = False
                return False

            # Bounded retry with backoff for transient errors
            self.last_error = self.sanitize_error(
                f"Cloudflare KV update attempt {attempt + 1}/{max_attempts} failed (HTTP {status}): {response_text[:200]}"
            )
            self._last_error_source = "kv"
            if attempt < len(delays):
                await self._sleep(delays[attempt])

        self.kv_update_accepted = False
        return False

    async def stop(self) -> None:
        """Gracefully stops the tunnel manager and owned cloudflared process."""
        self._stopped = True

        # 1. Cancel background monitoring tasks
        for task in (self._probe_task, self._monitor_task):
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        self._probe_task = None
        self._monitor_task = None

        # 2. Terminate owned cloudflared process
        if self.process and self.pid and self.start_ticks:
            if self.is_process_running():
                try:
                    # Terminate process group to catch children
                    if get_process_identity(self.pid) == self.start_ticks:
                        os.killpg(self.pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    if get_process_identity(self.pid) == self.start_ticks:
                        try:
                            self.process.terminate()
                        except ProcessLookupError:
                            pass

                # Wait up to 4.0 seconds
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=4.0)
                except asyncio.TimeoutError:
                    try:
                        if get_process_identity(self.pid) == self.start_ticks:
                            os.killpg(self.pid, signal.SIGKILL)
                    except (ProcessLookupError, PermissionError):
                        if get_process_identity(self.pid) == self.start_ticks:
                            try:
                                self.process.kill()
                            except ProcessLookupError:
                                pass

        self.process = None
        self.pid = None
        self.start_ticks = None
        self.target_reachable = False

        # 3. Release single-instance file lock
        self._release_lock()

    def snapshot(self) -> Dict[str, Any]:
        """Returns the sanitized runtime snapshot of the tunnel manager."""
        return TunnelSnapshot(
            enabled=self.enabled,
            running=self.is_process_running(),
            pid=self.pid,
            tunnel_url=self.current_tunnel_url,
            worker_static_url=self.worker_static_url,
            target_reachable=self.target_reachable,
            target_probed_at=self.last_probed_at,
            kv_update_accepted=self.kv_update_accepted,
            kv_written_at=self.last_kv_written_at,
            last_error=self.sanitize_error(self.last_error),
        ).to_dict()
