import asyncio
import json
import signal
from types import SimpleNamespace

import pytest

from app.tunnel_manager import TunnelManager, parse_tunnel_url_from_output, validate_trycloudflare_url


@pytest.mark.parametrize("url,valid", [
    ("https://abc.trycloudflare.com", True),
    ("https://trycloudflare.com", False),
    ("http://abc.trycloudflare.com", False),
    ("https://abc.trycloudflare.com.evil.test", False),
    ("https://u@abc.trycloudflare.com", False),
    ("https://abc.trycloudflare.com/path", False),
    ("https://abc.trycloudflare.com/?x=1", False),
    ("https://abc.trycloudflare.com:444", False),
    ("https://abc.trycloudflare.com:abc/", False),
])
def test_url_contract(url, valid):
    assert bool(validate_trycloudflare_url(url)) is valid


def test_parser_reads_only_contract_url():
    assert parse_tunnel_url_from_output("INF https://abc.trycloudflare.com") == "https://abc.trycloudflare.com/"
    assert parse_tunnel_url_from_output("https://abc.trycloudflare.com.evil.test") is None


def test_probe_requires_same_service_instance_and_https_target():
    seen = []
    def request(url, **kwargs):
        seen.append(url)
        return 200, json.dumps({"service": "mobile-web-voice-text-controller", "instance_id": "same"})
    manager = TunnelManager(instance_id="same", http_request=request)
    assert asyncio.run(manager._probe_health("https://abc.trycloudflare.com/"))
    assert seen == ["http://127.0.0.1:8000/api/v1/health", "https://abc.trycloudflare.com/api/v1/health"]
    manager.instance_id = "different"
    assert not asyncio.run(manager._probe_health("https://abc.trycloudflare.com/"))
    assert not asyncio.run(manager._probe_health("http://evil.trycloudflare.com/"))


def test_invalid_probe_never_writes_kv():
    calls = []
    async def run():
        def request(url, **kwargs):
            calls.append(url)
            return 503, ""
        manager = TunnelManager(instance_id="same", http_request=request)
        assert not await manager._probe_health("https://abc.trycloudflare.com/")
        assert len(calls) == 1
        assert not any("api.cloudflare.com" in url for url in calls)
    asyncio.run(run())


def test_kv_retry_is_bounded_and_auth_failure_stops():
    async def run(statuses, expected_calls, expected_delays):
        calls, delays = [], []
        def request(url, **kwargs):
            calls.append(kwargs.get("method", "GET"))
            status = statuses[min(len(calls)-1, len(statuses)-1)]
            return status, json.dumps({"success": status == 200})
        async def sleep(delay): delays.append(delay)
        manager = TunnelManager(cf_api_token="secret-token", cf_account_id="a", cf_namespace_id="n",
                                http_request=request, sleep=sleep)
        ok = await manager._write_kv_with_retry("https://abc.trycloudflare.com/")
        assert ok is (expected_calls == 1 and statuses[0] == 200)
        assert len(calls) == expected_calls
        assert delays == expected_delays
        assert "secret-token" not in (manager.snapshot()["last_error"] or "")
    asyncio.run(run([500, 500, 500], 3, [2.0, 4.0]))
    asyncio.run(run([403, 200], 1, []))
    asyncio.run(run([200], 1, []))


def test_lock_is_keyed_and_blocks_second_manager(tmp_path, monkeypatch):
    monkeypatch.setattr("app.tunnel_manager.Path.home", lambda: tmp_path)
    first = TunnelManager(cf_account_id="a", cf_namespace_id="n", cf_key="robot_url")
    second = TunnelManager(cf_account_id="a", cf_namespace_id="n", cf_key="robot_url")
    assert first._acquire_lock()
    assert not second._acquire_lock()
    second._release_lock()
    first._release_lock()


def test_staff_snapshot_distinguishes_process_and_reachability():
    manager = TunnelManager(enabled=True)
    data = manager.snapshot()
    assert data["running"] is False
    assert data["target_reachable"] is False


def test_shutdown_cancels_retry_without_more_api_calls():
    async def run():
        calls = []
        async def request(url, **kwargs):
            calls.append(url)
            await asyncio.sleep(30)
            return 500, ""
        manager = TunnelManager(cf_api_token="token", cf_account_id="a", cf_namespace_id="n", http_request=request)
        task = asyncio.create_task(manager._write_kv_with_retry("https://abc.trycloudflare.com/"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(calls) == 1
    asyncio.run(run())


def test_manager_start_stop_owns_fake_process_and_terminates_it(monkeypatch):
    signals = []
    class Stream:
        async def readline(self):
            await asyncio.sleep(60)
    class FakeProcess:
        pid = 43210
        returncode = None
        stdout = Stream()
        async def wait(self):
            self.returncode = 0
            return 0
        def terminate(self): signals.append("terminate")
        def kill(self): signals.append("kill")
    async def run():
        process = FakeProcess()
        monkeypatch.setattr("app.tunnel_manager.shutil.which", lambda _: "/fake/cloudflared")
        monkeypatch.setattr("app.tunnel_manager.get_process_identity", lambda pid: "boot:123")
        monkeypatch.setattr("app.tunnel_manager.os.killpg", lambda pid, sig: signals.append(sig))
        monkeypatch.setattr("app.tunnel_manager.asyncio.create_subprocess_exec", lambda *a, **k: asyncio.sleep(0, result=process))
        manager = TunnelManager(enabled=True, http_request=lambda *a, **k: (503, ""))
        monkeypatch.setattr(manager, "_acquire_lock", lambda: True)
        await manager.start()
        assert manager.is_process_running()
        await manager.stop()
        assert signal.SIGTERM in signals
        assert manager._lock_fd is None
    import signal
    asyncio.run(run())


def test_stop_does_not_signal_when_process_identity_changed(monkeypatch):
    signals = []
    class FakeProcess:
        pid = 43210
        returncode = None
        async def wait(self): raise AssertionError("must not wait on a process we no longer own")
    async def run():
        process = FakeProcess()
        manager = TunnelManager(enabled=True)
        manager.process, manager.pid, manager.start_ticks = process, process.pid, "old-identity"
        monkeypatch.setattr("app.tunnel_manager.get_process_identity", lambda pid: "replacement-process")
        monkeypatch.setattr("app.tunnel_manager.os.killpg", lambda *a: signals.append(a))
        monkeypatch.setattr(manager, "_release_lock", lambda: None)
        await manager.stop()
        assert signals == []
    asyncio.run(run())


def test_manager_stop_escalates_term_to_kill(monkeypatch):
    signals = []
    class FakeProcess:
        pid = 43210
        returncode = None
        async def wait(self): raise asyncio.TimeoutError
        def kill(self): signals.append("direct-kill")
    async def run():
        process = FakeProcess()
        manager = TunnelManager(enabled=True)
        manager.process, manager.pid, manager.start_ticks = process, process.pid, "owned"
        monkeypatch.setattr("app.tunnel_manager.get_process_identity", lambda pid: "owned")
        monkeypatch.setattr("app.tunnel_manager.os.killpg", lambda pid, sig: signals.append(sig))
        monkeypatch.setattr(manager, "_release_lock", lambda: None)
        async def wait_for(coro, timeout):
            await coro
            raise asyncio.TimeoutError
        monkeypatch.setattr("app.tunnel_manager.asyncio.wait_for", wait_for)
        await manager.stop()
        assert signals == [signal.SIGTERM, signal.SIGKILL]
    import signal
    asyncio.run(run())


def test_loop_preserves_kv_acceptance_and_clears_probe_error_after_recovery():
    async def run():
        manager = TunnelManager(enabled=True, probe_interval_sec=3)
        manager.current_tunnel_url = "https://abc.trycloudflare.com/"
        manager.process = SimpleNamespace(returncode=None)
        manager.pid, manager.start_ticks = 10, "owned"
        manager.is_process_running = lambda: True
        manager._read_existing_kv = lambda: asyncio.sleep(0, result=manager.current_tunnel_url)
        probe_results = iter([False, True])
        manager._probe_health = lambda _: asyncio.sleep(0, result=next(probe_results))
        sleeps = 0
        async def sleep(_):
            nonlocal sleeps
            sleeps += 1
            if sleeps == 2:
                assert manager.last_error is None
                assert manager.kv_update_accepted is True
                manager._stopped = True
        manager._sleep = sleep
        await manager._probe_and_update_loop()
        assert manager.target_reachable is True
        assert manager.kv_update_accepted is True
        assert manager.last_error is None
        assert manager._last_error_source is None
    asyncio.run(run())


def test_loop_does_not_repeat_rejected_kv_write_for_same_url():
    async def run():
        manager = TunnelManager(enabled=True)
        manager.current_tunnel_url = "https://abc.trycloudflare.com/"
        manager.process = SimpleNamespace(returncode=None)
        manager.pid, manager.start_ticks = 10, "owned"
        manager.is_process_running = lambda: True
        manager.cf_api_token, manager.cf_account_id, manager.cf_namespace_id = "token", "account", "namespace"
        manager._read_existing_kv = lambda: asyncio.sleep(0, result=None)
        manager._probe_health = lambda _: asyncio.sleep(0, result=True)
        writes = []
        async def write(url):
            writes.append(url)
            manager.last_error = "Cloudflare KV update rejected with HTTP 403"
            manager._last_error_source = "kv"
            return False
        manager._write_kv_with_retry = write
        count = 0
        async def sleep(_):
            nonlocal count
            count += 1
            if count == 3: manager._stopped = True
        manager._sleep = sleep
        await manager._probe_and_update_loop()
        assert writes == [manager.current_tunnel_url]
        assert manager.target_reachable is True
        assert manager.last_error == "Cloudflare KV update rejected with HTTP 403"
    asyncio.run(run())


def test_tunnel_start_failure_does_not_block_backend_health(monkeypatch):
    from app import main
    from app.session_manager import SessionManager

    class FakeBridge:
        def set_subtitle_callback(self, callback): pass
        def existing_agent_responds(self): return False
        def shutdown(self): pass

    class FakeProcesses:
        def __init__(self, *args, **kwargs): pass
        async def open(self): pass
        async def close(self): pass

    class FakeHealth:
        def __init__(self, *args, **kwargs): pass
        def start(self): pass
        async def close(self): pass

    class BrokenTunnelManager:
        def __init__(self, **kwargs):
            self.last_error = None
        async def start(self):
            raise RuntimeError("simulated cloudflared failure")
        async def stop(self): pass

    async def idle_watchdog():
        await asyncio.Event().wait()

    async def run():
        monkeypatch.setattr(main, "create_ros2_bridge", lambda *args: FakeBridge())
        monkeypatch.setattr(main, "session_manager", SessionManager())
        monkeypatch.setattr(main, "AgentProcesses", FakeProcesses)
        monkeypatch.setattr(main, "SystemHealth", FakeHealth)
        monkeypatch.setattr(main, "TunnelManager", BrokenTunnelManager)
        monkeypatch.setattr(main, "session_watchdog_loop", idle_watchdog)
        monkeypatch.setattr(main.settings, "ENABLE_TUNNEL", True)
        async with main.lifespan(main.app):
            response = await main.service_health()
            assert response.status_code == 200
            assert response.body
            assert main.tunnel_manager.last_error == "Tunnel manager failed to start (RuntimeError)"

    asyncio.run(run())
