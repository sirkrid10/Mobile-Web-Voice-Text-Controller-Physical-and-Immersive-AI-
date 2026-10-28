"""Read-only versioned subtitle WebSocket stream, owned by the asyncio loop."""

import asyncio
import json
import logging
import uuid

from starlette.websockets import WebSocketDisconnect

MAX_PACKET_BYTES = 16_384
LOGGER = logging.getLogger(__name__)


class VRSubtitleHub:
    """Keep the latest accepted caption, never queue an unbounded history."""

    def __init__(self, max_clients=16, send_timeout=5.0):
        self.max_clients = max_clients
        self.send_timeout = send_timeout
        self._clients = set()
        self.reset()

    def reset(self):
        self.stream_id = uuid.uuid4().hex
        self.sequence = 0
        self.latest = self._encode('', 0, '', '', 0)

    def _encode(self, text, stamp_ms, request_id, observation_id, sequence):
        return json.dumps({
            'type': 'subtitle', 'version': 1, 'stream_id': self.stream_id,
            'sequence': sequence, 'text': text, 'source_stamp_unix_ms': stamp_ms,
            'request_id': request_id, 'observation_id': observation_id,
        }, ensure_ascii=False, separators=(',', ':'))

    def publish(self, text, stamp, request_id='', observation_id=''):
        # Empty ROS messages are TTL clears, not a new displayed caption.
        if not text.strip():
            return
        packet = self._encode(text, round(stamp * 1000), request_id, observation_id,
                              self.sequence + 1)
        if len(packet.encode('utf-8')) > MAX_PACKET_BYTES:
            LOGGER.warning('VR subtitle packet exceeds the size limit; skipped')
            return
        self.sequence += 1
        self.latest = packet
        for queue in self._clients:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(packet)

    async def serve(self, websocket):
        await websocket.accept()
        if len(self._clients) >= self.max_clients:
            await websocket.close(code=1013, reason='VR subtitle capacity reached')
            return
        queue = asyncio.Queue(maxsize=1)
        queue.put_nowait(self.latest)
        self._clients.add(queue)

        async def send():
            while True:
                packet = await queue.get()
                await asyncio.wait_for(websocket.send_text(packet), self.send_timeout)

        async def receive():
            while True:
                message = await websocket.receive()
                if message['type'] == 'websocket.disconnect':
                    return
                # Incoming text/binary messages never execute application commands.

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, RuntimeError, asyncio.TimeoutError):
            pass
        finally:
            self._clients.discard(queue)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                await websocket.close()
            except (RuntimeError, WebSocketDisconnect):
                pass
