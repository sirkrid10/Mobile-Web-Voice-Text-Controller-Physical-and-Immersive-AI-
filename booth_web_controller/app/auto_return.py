"""Own the delayed return task and its eligibility policy."""

import asyncio

from app.config import settings


class AutoReturn:
    def __init__(self):
        self.task = None

    def cancel_pending(self):
        """Cancel a pending grace period when a new visitor claims control."""
        if self.task and not self.task.done():
            self.task.cancel()
            self.task = None
            return True
        return False

    def schedule(self, manager):
        """Replace a pending return with the current session's grace period."""
        self.cancel_pending()
        self.task = asyncio.create_task(self.run(manager))

    @staticmethod
    def eligible(enabled, reason, current_goal):
        return (enabled and reason in ("user_disconnect", "inactivity_timeout")
                and current_goal != settings.START_BOOTH_ID)

    async def run(self, manager):
        try:
            print(f"[SessionManager] Auto-return waiting {manager.auto_return_delay_sec}s grace period...")
            await asyncio.sleep(manager.auto_return_delay_sec)

            async with manager._lock:
                if manager.identity.active_session_id is not None:
                    print("[SessionManager] Auto-return aborted: new session was claimed.")
                    return

                print("[SessionManager] Executing Auto-Return to START_BOOTH...")
                manager.display.current_goal = settings.START_BOOTH_ID
                manager.display.heard_text = "กลับจุดเริ่มต้น (Auto-Return)"
                manager.display.llm_explanation = "หมดเวลากิจกรรม กำลังนำหุ่นยนต์เดินกลับจุดเริ่มต้นหน้าร้าน"

                if manager.ros_bridge:
                    manager.ros_bridge.publish_high_level_action(
                        action="GO_TO",
                        target=settings.START_BOOTH_ID,
                        explanation="Auto-returning to Start Booth after session ended",
                        source="auto_return"
                    )

            manager._trigger_broadcast()
        except asyncio.CancelledError:
            print("[SessionManager] Delayed auto-return task was cancelled.")
