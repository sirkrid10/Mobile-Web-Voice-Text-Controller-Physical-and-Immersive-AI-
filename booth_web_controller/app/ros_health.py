"""Bounded parameter reads through the existing executor, without a ROS CLI daemon."""

import asyncio


async def probe_parameters(client, names, timeout=2):
    if not client.services_are_ready():
        return 'not_observed'
    future = client.get_parameters(names)
    loop = asyncio.get_running_loop()
    waiter = loop.create_future()

    def completed(done):
        try:
            response = done.result()
            status = 'responding' if response is not None and len(response.values) == len(names) else 'invalid_response'
        except Exception:
            status = 'failed'

        def deliver():
            if not waiter.done():
                waiter.set_result(status)
        try:
            loop.call_soon_threadsafe(deliver)
        except RuntimeError:
            pass

    future.add_done_callback(completed)
    try:
        return await asyncio.wait_for(waiter, timeout)
    except asyncio.TimeoutError:
        future.cancel()
        return 'timeout'
    except asyncio.CancelledError:
        future.cancel()
        raise
