"""Read and set only subtitle_mode through an existing ROS parameter client."""

import asyncio


class SubtitleModeError(RuntimeError):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class SubtitleModeControl:
    """Bridge ROS futures to asyncio without spinning or blocking the web loop."""

    def __init__(self, client, make_parameter, timeout_sec=2.0):
        self.client = client
        self.make_parameter = make_parameter
        self.timeout_sec = timeout_sec
        self._lock = asyncio.Lock()

    async def _call(self, method, argument):
        try:
            ready = self.client.services_are_ready()
        except Exception:
            ready = False
        if not ready:
            raise SubtitleModeError(503, 'Subtitle node is unavailable; check it is running on the same ROS profile')
        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        try:
            future = getattr(self.client, method)(argument)
        except Exception:
            raise SubtitleModeError(503, 'Could not contact subtitle node') from None

        def deliver(result, error):
            if waiter.done():
                return
            if error:
                waiter.set_exception(SubtitleModeError(503, 'Subtitle node request failed'))
            else:
                waiter.set_result(result)

        def completed(done):
            try:
                result, error = done.result(), None
            except Exception as exc:
                result, error = None, exc
            try:
                loop.call_soon_threadsafe(deliver, result, error)
            except RuntimeError:
                pass  # The HTTP event loop has already shut down.

        future.add_done_callback(completed)
        try:
            return await asyncio.wait_for(waiter, timeout=self.timeout_sec)
        except asyncio.TimeoutError:
            future.cancel()
            raise SubtitleModeError(504, 'Subtitle mode could not be confirmed; read the current mode before retrying') from None
        except asyncio.CancelledError:
            future.cancel()
            raise

    async def _read(self):
        response = await self._call('get_parameters', ['subtitle_mode'])
        try:
            value, = response.values
            mode = value.string_value
            valid = value.type == 4 and mode in ('standard', 'friendly')
        except (AttributeError, ValueError, TypeError):
            valid = False
        if not valid:
            raise SubtitleModeError(503, 'Subtitle node does not expose a supported subtitle_mode')
        return mode

    async def read(self):
        if self._lock.locked():
            raise SubtitleModeError(409, 'Another subtitle mode request is in progress')
        async with self._lock:
            return await self._read()

    async def write(self, mode):
        if mode not in ('standard', 'friendly'):
            raise SubtitleModeError(422, 'Choose standard or friendly')
        if self._lock.locked():
            raise SubtitleModeError(409, 'Another subtitle mode request is in progress')
        async with self._lock:
            response = await self._call('set_parameters_atomically', [self.make_parameter(mode)])
            if not getattr(getattr(response, 'result', None), 'successful', False):
                raise SubtitleModeError(409, 'Subtitle node rejected the mode change')
            observed = await self._read()
            if observed != mode:
                raise SubtitleModeError(409, 'Subtitle mode changed before confirmation; read the current mode again')
            return observed
