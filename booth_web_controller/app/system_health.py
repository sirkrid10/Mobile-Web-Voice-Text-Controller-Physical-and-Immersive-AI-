"""Cached, read-only connectivity observations. Never dispatch a Robot goal."""

import asyncio
import json
import os
import time
from pathlib import Path


async def run_probe(*argv, timeout=3):
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout)
        return process.returncode, stdout.decode(errors='replace')[:1_000_000]
    except (OSError, asyncio.TimeoutError):
        return None, ''
    finally:
        if process and process.returncode is None:
            process.kill()
            await process.wait()


async def tailscale_health(server):
    code, output = await run_probe('tailscale', 'status', '--json')
    if code != 0:
        return {'status': 'unknown', 'detail': 'Cannot read tailscale status; service, command or permission may be unavailable'}
    try:
        state = json.loads(output)
        active = state.get('BackendState') == 'Running'
        peers = state.get('Peer') or {}
        peer = next((v for v in peers.values() if server in v.get('TailscaleIPs', [])), None)
        result = {'status': 'connected' if active else 'disconnected',
                  'local_ips': state.get('TailscaleIPs', []), 'server': server,
                  'server_online': peer.get('Online') if peer else None, 'reachable': None}
        if active and server:
            ping_code, _ = await run_probe('tailscale', 'ping', '--c', '1', '--timeout', '2s', '--until-direct=false', server)
            result['reachable'] = ping_code == 0 if ping_code is not None else None
        return result
    except (ValueError, AttributeError, TypeError):
        return {'status': 'unknown', 'detail': 'Tailscale returned an unreadable status'}


class SystemHealth:
    def __init__(self, bridge, processes, hub, *, mock=False, tunnel_manager=None):
        self.bridge = bridge
        self.processes = processes
        self.hub = hub
        self.mock = mock
        self.tunnel_manager = tunnel_manager
        self.latest = {'checked_at': None, 'mock': mock, 'ros': {}, 'tailscale': {'status': 'checking'}}
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self._watch())

    async def _watch(self):
        while True:
            try:
                server = os.environ.get('TURTLEBOT_TAILSCALE_SERVER_IP') or os.environ.get('ROS_DISCOVERY_SERVER', '').split(':')[0]
                ros, tailscale, _ = await asyncio.gather(
                    self.bridge.inspect_connections(),
                    tailscale_health(server) if not self.mock else asyncio.sleep(0, result={'status': 'mock'}),
                    self.processes.refresh_external(),
                )
                self.latest = {'checked_at': time.time(), 'mock': self.mock, 'ros': ros, 'tailscale': tailscale}
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.latest = {'checked_at': time.time(), 'mock': self.mock, 'ros': {},
                               'tailscale': {'status': 'unknown'}, 'error': f'Health check failed ({type(exc).__name__})'}
            await asyncio.sleep(5)

    def snapshot(self):
        tunnel_data = self.tunnel_manager.snapshot() if self.tunnel_manager else {
            'enabled': False, 'running': False, 'pid': None, 'tunnel_url': None,
            'worker_static_url': None, 'target_reachable': False, 'target_probed_at': None,
            'kv_update_accepted': False, 'kv_written_at': None, 'last_error': None,
        }
        result = {
            **self.latest,
            'backend_directory': str(Path(__file__).resolve().parents[2]),
            'processes': self.processes.snapshot(),
            'vr': self.hub.inspection(),
            'tunnel': tunnel_data,
        }
        ros = dict(result.get('ros', {}))
        ros.update(self.bridge.robot_observation())
        received_at = ros.get('robot_received_at')
        source_at = ros.get('robot_source_at')
        now = time.time()
        ros['robot_receive_age_sec'] = max(0, now - received_at) if received_at else None
        ros['robot_source_age_sec'] = now - source_at if source_at else None
        ros['robot_fresh'] = bool(received_at and source_at and now - received_at <= 3 and -0.6 <= now - source_at <= 3)
        result['ros'] = ros
        return result

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
