"""Staff-only mode control: HTTP authorization, ROS errors, and real ROS service calls."""

import asyncio
from concurrent.futures import Future
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app import main as backend
from app.config import settings
from app.subtitle_mode import SubtitleModeControl, SubtitleModeError


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
async def api(monkeypatch):
    bridge = SimpleNamespace(read_subtitle_mode=AsyncMock(return_value='standard'),
                             set_subtitle_mode=AsyncMock(return_value='friendly'))
    monkeypatch.setattr(backend, 'ros_bridge_instance', bridge)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url='http://test') as client:
        yield client, bridge, {'X-Staff-Pin': settings.STAFF_PIN}


@pytest.mark.anyio
async def test_pin_required_for_both_read_and_write(api):
    client, bridge, headers = api
    assert (await client.get('/api/v1/staff/subtitle-mode')).status_code == 401
    assert (await client.post('/api/v1/staff/subtitle-mode', json={'mode': 'friendly'})).status_code == 401
    bridge.read_subtitle_mode.assert_not_called()
    bridge.set_subtitle_mode.assert_not_called()


@pytest.mark.anyio
async def test_read_and_confirmed_write(api):
    client, bridge, headers = api
    response = await client.get('/api/v1/staff/subtitle-mode', headers=headers)
    assert response.status_code == 200 and response.json() == {'mode': 'standard'}
    response = await client.post('/api/v1/staff/subtitle-mode', json={'mode': 'friendly'}, headers=headers)
    assert response.status_code == 200 and response.json() == {'mode': 'friendly'}
    bridge.set_subtitle_mode.assert_awaited_once_with('friendly')


@pytest.mark.parametrize('body', [{'mode': 'bad'}, {'mode': 1}, {},
                                  {'mode': 'friendly', 'node': '/robot'}])
@pytest.mark.anyio
async def test_only_allowed_modes_can_be_written(api, body):
    client, bridge, headers = api
    assert (await client.post('/api/v1/staff/subtitle-mode', json=body, headers=headers)).status_code == 422
    bridge.set_subtitle_mode.assert_not_called()


@pytest.mark.parametrize('status', [409, 503, 504])
@pytest.mark.anyio
async def test_transport_failure_is_not_reported_as_success(api, status):
    client, bridge, headers = api
    bridge.set_subtitle_mode.side_effect = SubtitleModeError(status, 'not confirmed')
    response = await client.post('/api/v1/staff/subtitle-mode', json={'mode': 'friendly'}, headers=headers)
    assert response.status_code == status
    assert 'mode' not in response.json()


@pytest.mark.anyio
async def test_missing_bridge_is_unavailable(api, monkeypatch):
    client, bridge, headers = api
    monkeypatch.setattr(backend, 'ros_bridge_instance', None)
    assert (await client.get('/api/v1/staff/subtitle-mode', headers=headers)).status_code == 503


def test_standalone_mock_does_not_fake_subtitle_mode():
    from app.ros2_bridge import MockROS2Bridge
    async def run():
        bridge = MockROS2Bridge(SimpleNamespace(), asyncio.get_running_loop())
        with pytest.raises(SubtitleModeError) as exc:
            await bridge.read_subtitle_mode()
        assert exc.value.status_code == 503
    asyncio.run(run())


class ParameterClient:
    ready = True
    reject = False
    observed = 'standard'
    def services_are_ready(self):
        return self.ready
    def get_parameters(self, names):
        assert names == ['subtitle_mode']
        future = Future()
        future.set_result(SimpleNamespace(values=[SimpleNamespace(type=4, string_value=self.observed)]))
        return future
    def set_parameters_atomically(self, parameters):
        if not self.reject:
            self.observed = parameters[0]
        future = Future()
        future.set_result(SimpleNamespace(result=SimpleNamespace(successful=not self.reject)))
        return future


def test_control_reads_after_setting_and_handles_rejection():
    async def run():
        client = ParameterClient()
        control = SubtitleModeControl(client, lambda mode: mode)
        assert await control.read() == 'standard'
        assert await control.write('friendly') == 'friendly'
        client.reject = True
        with pytest.raises(SubtitleModeError) as exc:
            await control.write('standard')
        assert exc.value.status_code == 409
        assert await control.read() == 'friendly'
        client.ready = False
        with pytest.raises(SubtitleModeError) as exc:
            await control.read()
        assert exc.value.status_code == 503
    asyncio.run(run())


def test_timeout_is_uncertain_and_late_response_is_ignored():
    async def run():
        future = Future()
        class Slow(ParameterClient):
            def set_parameters_atomically(self, values):
                return future
        control = SubtitleModeControl(Slow(), lambda mode: mode, timeout_sec=0.01)
        with pytest.raises(SubtitleModeError) as exc:
            await control.write('friendly')
        assert exc.value.status_code == 504
        assert future.cancelled()
        await asyncio.sleep(0)
    asyncio.run(run())


def test_busy_requests_do_not_queue_more_parameter_writes():
    async def run():
        future = Future()
        class Slow(ParameterClient):
            def get_parameters(self, names):
                return future
        control = SubtitleModeControl(Slow(), lambda mode: mode, timeout_sec=0.02)
        first = asyncio.create_task(control.read())
        await asyncio.sleep(0)
        with pytest.raises(SubtitleModeError) as exc:
            await control.write('friendly')
        assert exc.value.status_code == 409
        with pytest.raises(SubtitleModeError):
            await first
    asyncio.run(run())


def test_real_ros_parameter_roundtrip_from_authenticated_http(monkeypatch):
    rclpy = pytest.importorskip('rclpy')
    from rclpy.executors import SingleThreadedExecutor
    from agent_pkg.subtitle_node import SubtitleNode
    from app.ros2_bridge import RealROS2Bridge
    from app.session_manager import SessionManager
    import httpx
    import threading
    class OfflineModel:
        def complete(self, job):
            return ''
        def close(self):
            pass
    async def run():
        monkeypatch.setattr(backend, 'session_manager', SessionManager())
        bridge = RealROS2Bridge(backend.session_manager, asyncio.get_running_loop())
        monkeypatch.setattr(backend, 'ros_bridge_instance', bridge)
        subtitle = SubtitleNode(subtitle_model=OfflineModel())
        executor = SingleThreadedExecutor()
        executor.add_node(subtitle)
        thread = threading.Thread(target=executor.spin, daemon=True)
        thread.start()
        # Sandbox may deny asyncio's cross-thread wakeup socket. Keep the test
        # loop ticking, as the production Backend watchdog also does.
        async def tick():
            while True:
                await asyncio.sleep(0.01)
        heartbeat = asyncio.create_task(tick())
        try:
            loop = asyncio.get_running_loop()
            until = loop.time() + 5
            while not bridge._subtitle_mode_control.client.services_are_ready() and loop.time() < until:
                await asyncio.sleep(0.02)
            headers = {'X-Staff-Pin': settings.STAFF_PIN}
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app), base_url='http://test') as client:
                read = await client.get('/api/v1/staff/subtitle-mode', headers=headers)
                assert read.status_code == 200 and read.json()['mode'] == 'standard'
                for mode in ('friendly', 'standard'):
                    changed = await client.post('/api/v1/staff/subtitle-mode', headers=headers, json={'mode': mode})
                    assert changed.status_code == 200 and changed.json()['mode'] == mode
                    assert subtitle.get_parameter('subtitle_mode').value == mode
                assert backend.session_manager.latest_action is None
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            executor.shutdown()
            thread.join(2)
            subtitle.destroy_node()
            bridge.shutdown()
    asyncio.run(run())


@pytest.mark.parametrize('parameter_type,mode', [(1, 'standard'), (4, 'unknown')])
def test_unexpected_parameter_response_is_unavailable(parameter_type, mode):
    async def run():
        class Malformed(ParameterClient):
            def get_parameters(self, names):
                future = Future()
                future.set_result(SimpleNamespace(values=[SimpleNamespace(type=parameter_type, string_value=mode)]))
                return future
        with pytest.raises(SubtitleModeError) as exc:
            await SubtitleModeControl(Malformed(), lambda mode: mode).read()
        assert exc.value.status_code == 503
    asyncio.run(run())


def test_readback_mismatch_is_not_a_success():
    async def run():
        class ChangedElsewhere(ParameterClient):
            def set_parameters_atomically(self, parameters):
                future = Future()
                future.set_result(SimpleNamespace(result=SimpleNamespace(successful=True)))
                return future
        with pytest.raises(SubtitleModeError) as exc:
            await SubtitleModeControl(ChangedElsewhere(), lambda mode: mode).write('friendly')
        assert exc.value.status_code == 409
    asyncio.run(run())
