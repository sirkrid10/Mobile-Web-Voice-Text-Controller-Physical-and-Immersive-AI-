"""Accept source-ordered subtitles and clear them at their deadlines."""

import asyncio, time


class SubtitleLifecycle:
    def __init__(self, session_manager, loop):
        self.session_manager = session_manager
        self.loop = loop
        self._subtitle_timer = None
        self._latest_subtitle_stamp = 0.0
        self._subtitle_generation = 0

    def set_subtitle_callback(self, callback):
        """Observe accepted captions without changing ROS or web state contracts."""
        self._subtitle_callback = callback

    def _accept_subtitle(self, stamp: float, deadline: float, text: str,
                         request_id: str = '', observation_id: str = ''):
        """Apply the newest source subtitle on the asyncio owner loop."""
        now = self._subtitle_now()
        if stamp <= 0 or stamp > now or stamp < self._latest_subtitle_stamp:
            return
        if text.strip() and deadline <= now:
            return

        self._latest_subtitle_stamp = stamp
        self._subtitle_generation += 1
        generation = self._subtitle_generation
        self._cancel_subtitle_timer()

        if not text.strip():
            self.session_manager.display.llm_explanation = ""
            self.session_manager._trigger_broadcast()
            return

        self.session_manager.update_from_llm_mind(
            heard_text=self.session_manager.display.heard_text,
            explanation=text,
        )
        self._schedule_subtitle_clear(deadline, generation)
        callback = getattr(self, '_subtitle_callback', None)
        if callback is not None:
            callback(text, stamp, request_id, observation_id)

    def _subtitle_now(self) -> float:
        return time.time()

    def _schedule_subtitle_clear(self, deadline: float, generation: int):
        async def _clear_at_deadline():
            try:
                while generation == self._subtitle_generation:
                    remaining = deadline - self._subtitle_now()
                    if remaining <= 0:
                        if generation == self._subtitle_generation:
                            self.session_manager.display.llm_explanation = ""
                            self.session_manager._trigger_broadcast()
                        return
                    await asyncio.sleep(remaining)
            except asyncio.CancelledError:
                pass

        self._subtitle_timer = asyncio.create_task(_clear_at_deadline())

    def _cancel_subtitle_timer(self):
        if self._subtitle_timer and not self._subtitle_timer.done():
            self._subtitle_timer.cancel()
        self._subtitle_timer = None
