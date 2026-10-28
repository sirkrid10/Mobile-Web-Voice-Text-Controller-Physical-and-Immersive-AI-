"""Versioned VR WebSocket contract, isolated from real API keys and robot goals."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from app import main as backend
from app.ros2_bridge import MockROS2Bridge
from app.vr_subtitle import MAX_PACKET_BYTES, VRSubtitleHub


class ASGISocket:
    """Exercise FastAPI's actual WebSocket route without opening network ports."""
    async def connect(self):
        self.incoming = asyncio.Queue()
        self.outgoing = asyncio.Queue()
        scope = dict(type='websocket', path='/ws/vr/subtitle', raw_path=b'/ws/vr/subtitle',
                     scheme='ws', root_path='', query_string=b'', headers=[], subprotocols=[],
                     client=('127.0.0.1', 1), server=('test', 80), http_version='1.1',
                     asgi={'version': '3.0', 'spec_version': '2.1'})
        await self.incoming.put({'type': 'websocket.connect'})
        self.task = asyncio.create_task(backend.app(scope, self.incoming.get, self.outgoing.put))
        assert (await asyncio.wait_for(self.outgoing.get(), 1))['type'] == 'websocket.accept'
        return self

    async def read(self):
        response = await asyncio.wait_for(self.outgoing.get(), 1)
        assert response['type'] == 'websocket.send'
        return json.loads(response['text'])

    async def close(self):
        await self.incoming.put({'type': 'websocket.disconnect', 'code': 1000})
        await asyncio.wait_for(self.task, 1)


def test_endpoint_schema_updates_clear_handling_and_reconnect(monkeypatch):
    async def run():
        hub = VRSubtitleHub()
        monkeypatch.setattr(backend, 'vr_subtitles', hub)
        first = await ASGISocket().connect()
        initial = await first.read()
        assert initial['type'] == 'subtitle' and initial['version'] == 1
        assert initial['sequence'] == 0 and initial['text'] == ''
        hub.publish('กำลังพาไปจุด B ครับ', 1000, 'request-one', 'observation-one')
        caption = await first.read()
        assert caption == dict(type='subtitle', version=1, stream_id=initial['stream_id'],
                               sequence=1, text='กำลังพาไปจุด B ครับ', source_stamp_unix_ms=1000000,
                               request_id='request-one', observation_id='observation-one')
        hub.publish('', 1001)
        assert hub.sequence == 1
        await first.incoming.put({'type': 'websocket.receive', 'text': 'go to A'})
        assert hub.sequence == 1  # Client messages never become robot commands.
        await first.close()
        assert not hub._clients
        second = await ASGISocket().connect()
        assert await second.read() == caption
        hub.publish('ถึงจุด B แล้วครับ', 1002, 'request-one')
        assert (await second.read())['sequence'] == 2
        await second.close()
    asyncio.run(run())


def test_bridge_forwards_only_accepted_nonempty_subtitles():
    async def run():
        hub = VRSubtitleHub()
        session = SimpleNamespace(heard_text='', llm_explanation='', _trigger_broadcast=lambda: None)
        def update(**kwargs):
            session.llm_explanation = kwargs['explanation']
        session.update_from_llm_mind = update
        bridge = MockROS2Bridge(session, asyncio.get_running_loop(), clock=lambda: 1000)
        bridge.set_subtitle_callback(hub.publish)
        try:
            bridge._accept_subtitle(990, 991, 'expired')
            bridge._accept_subtitle(1001, 1002, 'future')
            assert hub.sequence == 0
            bridge._accept_subtitle(999, 1001, 'พร้อมแล้วครับ', 'req', 'obs')
            assert json.loads(hub.latest)['request_id'] == 'req'
            assert json.loads(hub.latest)['observation_id'] == 'obs'
            bridge._accept_subtitle(998, 1001, 'out of order')
            bridge._accept_subtitle(1000, 1000, '')
            assert hub.sequence == 1
            assert session.llm_explanation == ''  # Existing web-state TTL is unchanged.
            assert json.loads(hub.latest)['text'] == 'พร้อมแล้วครับ'
        finally:
            bridge.shutdown()
    asyncio.run(run())


class SlowSocket:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.disconnected = asyncio.Event()
        self.sent = []
        self.close_codes = []
    async def accept(self):
        pass
    async def send_text(self, data):
        self.started.set()
        await self.release.wait()
        self.sent.append(json.loads(data))
    async def receive(self):
        await self.disconnected.wait()
        return {'type': 'websocket.disconnect'}
    async def close(self, code=1000, reason=''):
        self.close_codes.append(code)


def test_slow_client_keeps_only_the_latest_pending_packet():
    async def run():
        hub = VRSubtitleHub()
        socket = SlowSocket()
        task = asyncio.create_task(hub.serve(socket))
        await socket.started.wait()
        for n in range(100):
            hub.publish(str(n), 1000 + n)
        assert len(hub._clients) == 1
        assert next(iter(hub._clients)).qsize() == 1
        socket.release.set()
        for _ in range(20):
            await asyncio.sleep(0)
            if len(socket.sent) >= 2:
                break
        assert [packet['text'] for packet in socket.sent] == ['', '99']
        socket.disconnected.set()
        await task
        assert not hub._clients
    asyncio.run(run())


def test_stalled_client_times_out_and_releases_capacity():
    async def run():
        hub = VRSubtitleHub(send_timeout=0.01)
        socket = SlowSocket()
        await asyncio.wait_for(hub.serve(socket), 1)
        assert not hub._clients
    asyncio.run(run())


def test_connection_limit_closes_extra_client():
    async def run():
        hub = VRSubtitleHub(max_clients=1)
        first = SlowSocket()
        task = asyncio.create_task(hub.serve(first))
        await first.started.wait()
        second = SlowSocket()
        await hub.serve(second)
        assert second.close_codes == [1013]
        assert len(hub._clients) == 1
        first.disconnected.set()
        await task
    asyncio.run(run())


def test_reset_starts_new_stream_and_oversized_packet_is_not_cached():
    hub = VRSubtitleHub()
    original = hub.stream_id
    hub.publish('ก' * MAX_PACKET_BYTES, 1000)
    assert hub.sequence == 0
    hub.publish('one', 1000)
    hub.reset()
    assert hub.sequence == 0 and hub.stream_id != original
    assert json.loads(hub.latest)['text'] == ''


def test_real_ros_subtitle_reaches_vr_websocket(monkeypatch):
    rclpy = pytest.importorskip('rclpy')
    from rclpy.executors import SingleThreadedExecutor
    from rclpy.node import Node
    from ai_interfaces.msg import Subtitle
    from app.ros2_bridge import RealROS2Bridge
    from app.session_manager import SessionManager
    import threading
    async def run():
        hub = VRSubtitleHub()
        monkeypatch.setattr(backend, 'vr_subtitles', hub)
        bridge = RealROS2Bridge(SessionManager(), asyncio.get_running_loop())
        bridge.set_subtitle_callback(hub.publish)
        publisher_node = Node('vr_subtitle_test_publisher')
        pub = publisher_node.create_publisher(Subtitle, '/vr/subtitle', 10)
        executor = SingleThreadedExecutor()
        executor.add_node(publisher_node)
        thread = threading.Thread(target=executor.spin, daemon=True)
        thread.start()
        async def tick():
            while True:
                await asyncio.sleep(0.01)
        heartbeat = asyncio.create_task(tick())
        socket = None
        try:
            until = asyncio.get_running_loop().time() + 5
            while pub.get_subscription_count() == 0 and asyncio.get_running_loop().time() < until:
                await asyncio.sleep(0.02)
            assert pub.get_subscription_count() > 0
            socket = await ASGISocket().connect()
            await socket.read()
            message = Subtitle()
            message.stamp = publisher_node.get_clock().now().to_msg()
            message.ttl.sec = 2
            message.text = 'ถึงจุด C แล้วครับ'
            message.request_id = 'vr-contract'
            message.observation_id = 'camera-trace'
            pub.publish(message)
            packet = await socket.read()
            assert packet['text'] == message.text
            assert packet['request_id'] == message.request_id
            assert packet['observation_id'] == message.observation_id
        finally:
            if socket:
                await socket.close()
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            executor.shutdown()
            thread.join(2)
            publisher_node.destroy_node()
            bridge.shutdown()
    asyncio.run(run())
