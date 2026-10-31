"""Simulate ROS requests and navigation for offline use."""

import time, secrets, asyncio, math
from typing import Optional, Dict, Any

from app.bridge_base import BaseROS2Bridge
from app.config import settings
from app.destinations import DESTINATION_IDS, SPOKEN_IDS, STATIONS
from app.models import DirectActionOutcome, IntentDispatchOutcome, IntentOutcome, RosStamp


class MockROS2Bridge(BaseROS2Bridge):
    def __init__(self, session_manager: Any, loop: asyncio.AbstractEventLoop, clock=None):
        super().__init__(session_manager, loop)
        self._sim_task: Optional[asyncio.Task] = None
        self._clock = clock or time.time
        print("[ROS2Bridge Mock] Running in standalone mock mode (USE_MOCK_ROS2=true).")

    def publish_user_transcript(self, request_id: str, session_id: str, input_mode: str, text: str):
        req_id = request_id
        print(f"[ROS2Bridge Mock] Published to /guide/user_request: req_id={req_id}, session_id={session_id}, text='{text}'")
        self.session_manager.update_from_llm_mind(
            heard_text=text,
            target=self.session_manager.display.current_goal,
            explanation=self.session_manager.display.llm_explanation,
        )
        target, status, message = self._mock_intent(text)
        if status == "NAVIGATE" and self._sim_task and not self._sim_task.done():
            self.session_manager.record_intent_result(IntentOutcome(
                request_id=req_id,
                session_id=session_id,
                stamp=RosStamp(sec=int(time.time()), nanosec=0),
                status="FAILED",
                message="หุ่นยังไม่ว่าง",
                error_code="robot_busy",
            ))
            self.handle_mock_subtitle("หุ่นยังไม่ว่าง กำลังทำคำสั่งก่อนหน้า", ttl_sec=5.0)
            return

        if status != "NAVIGATE":
            self.session_manager.record_intent_result(IntentOutcome(
                request_id=req_id,
                session_id=session_id,
                stamp=RosStamp(sec=int(time.time()), nanosec=0),
                status=status,
                message=message,
            ))
            return

        if target:
            target_name = self._location_name(target)
            self.session_manager.update_from_llm_mind(
                heard_text=text,
                target=target,
                explanation=f"intent_node เลือกปลายทาง: {target} ({target_name})"
            )
            self.session_manager.record_intent_result(IntentOutcome(
                request_id=req_id,
                session_id=session_id,
                stamp=RosStamp(sec=int(time.time()), nanosec=0),
                status="NAVIGATE",
                destination_id=target
            ))
            self._start_navigation_simulation(target)
            self.session_manager.record_intent_dispatch(IntentDispatchOutcome(
                request_id=req_id, session_id=session_id,
                stamp=RosStamp(sec=int(time.time()), nanosec=0),
                destination_id=target, status="simulated",
            ))

    @staticmethod
    def _normalize_mock_text(text: str) -> str:
        import re
        normalized = text.strip().lower()
        normalized = re.sub(r"[^a-z0-9ก-๙]+", " ", normalized)
        return " ".join(normalized.split())

    @classmethod
    def _mock_intent(cls, text: str):
        import re
        normalized = cls._normalize_mock_text(text)
        if re.fullmatch(r'(?:ช่วย\s*)?(?:พา\s*)?กลับ\s*(?:ไป\s*)?(?:จุดเริ่มต้น|start)(?:\s*(?:ครับ|ค่ะ|หน่อย|ด้วย))*|(?:return|go back) to start(?: please)?', normalized):
            return settings.START_BOOTH_ID, "NAVIGATE", ""
        found = set(re.findall(r'(?<![a-z0-9])[abcd](?![a-z0-9])', normalized))
        for identifier, name in SPOKEN_IDS.items():
            if re.search(r'(?:จุด|สถานี)\s*' + name, normalized):
                found.add(identifier.lower())
        for station in STATIONS:
            if any(cls._normalize_mock_text(alias) in normalized for alias in station['aliases']):
                found.add(station['id'].lower())
        if len(found) > 1 or re.search(r'ไม่\s*(?:ไป|พา)|อย่า|ไม่เอา|\bnot\b', normalized):
            return "", "CLARIFY", "ระบุปลายทางเพียงจุดเดียว"
        movement = any(word in normalized for word in ('ไป', 'พา', 'กลับ')) or re.search(r'\b(?:navigate|go|take me|return)\b', normalized)
        if len(found) == 1 and movement:
            return next(iter(found)).upper(), "NAVIGATE", ""
        if any(word in normalized for word in ("wait", "รอ", "หยุด", "stop", "cancel")):
            return "", "UNSUPPORTED", "คำสั่งนี้ยังไม่รองรับ"
        choices = ", ".join(DESTINATION_IDS[:-1]) + " หรือ " + DESTINATION_IDS[-1]
        return "", "CLARIFY", f"กรุณาระบุจุด {choices}"

    @staticmethod
    def _location_name(target: str) -> str:
        location = next((item for item in settings.LOCATIONS if item["id"] == target), None)
        return location["label"] if location else target

    def publish_high_level_action(self, action: str, target: str, explanation: str, source: str = "web_controller"):
        print(f"[ROS2Bridge Mock] Direct navigation action requested: target={target}, source={source}")
        self.send_navigation_goal(destination_id=target, source=source)

    def send_navigation_goal(self, destination_id: str, request_id: Optional[str] = None, source: str = "web_controller"):
        req_id = request_id or f"req-{secrets.token_hex(4)}"
        print(f"[ROS2Bridge Mock] Action /guide/navigate Goal sent: req_id={req_id}, dest={destination_id}")
        context = {"request_id": req_id, "source": source, "destination_id": destination_id}
        self.session_manager.record_action_outcome(DirectActionOutcome(**context, outcome="sending"))
        self.session_manager.record_action_outcome(DirectActionOutcome(**context, outcome="accepted"))
        self.cancel_navigation_goal()
        self._start_navigation_simulation(destination_id, context)

    def cancel_navigation_goal(self):
        if self._sim_task and not self._sim_task.done():
            self._sim_task.cancel()
            self._sim_task = None
            print("[ROS2Bridge Mock] Cancelled active navigation Action goal.")

    def publish_emergency_stop(self):
        self.cancel_navigation_goal()
        self.session_manager.update_from_ros_state(state="STOPPED")
        print("[ROS2Bridge Mock] Emergency stop executed.")

    def handle_mock_subtitle(self, text: str, ttl_sec: float = 5.0, stamp_sec: float = 0.0):
        """Simulate receiving Subtitle message."""
        stamp = stamp_sec or self._subtitle_now()
        if not math.isfinite(stamp) or not math.isfinite(ttl_sec) or stamp <= 0 or ttl_sec < 0:
            return
        deadline = stamp + ttl_sec
        if not math.isfinite(deadline):
            return
        self.loop.call_soon_threadsafe(self._accept_subtitle, stamp, deadline, text or "")

    def _subtitle_now(self) -> float:
        return self._clock()

    def inject_system_state(self, state: str, goal: Optional[str] = None,
                            obstacle_detected: bool = False, pose: Optional[Dict[str, float]] = None):
        self.session_manager.update_from_ros_state(
            state=state, goal=goal, obstacle_detected=obstacle_detected, pose=pose
        )

    def _start_navigation_simulation(self, target: str, action_context: Optional[Dict[str, str]] = None):
        if self._sim_task and not self._sim_task.done():
            return

        async def _run_sim():
            try:
                target_name = self._location_name(target)
                # 1. Start navigating (phase: NAVIGATING)
                self.session_manager.update_from_ros_state(state="NAVIGATING", goal=target)
                self.session_manager.update_from_llm_mind(
                    heard_text=self.session_manager.display.heard_text,
                    target=target,
                    explanation=f"กำลังนำทางไป{target_name}"
                )
                print(f"[ROS2Bridge Mock] Navigating towards {target}...")
                await asyncio.sleep(4.0)

                # A/B/C/D, including return to D, all finish at ARRIVED.
                self.session_manager.update_from_ros_state(state="REACHED", goal=target)
                self.session_manager.update_from_llm_mind(
                    heard_text=self.session_manager.display.heard_text,
                    target=target,
                    explanation=f"หุ่นยนต์เดินทางถึง {target_name} เรียบร้อยแล้ว พร้อมรับคำสั่งถัดไป"
                )
                if action_context:
                    self.session_manager.record_action_outcome(DirectActionOutcome(
                        **action_context,
                        outcome="succeeded",
                        ros_status=4,
                        error_code=0,
                        error_msg="Mock navigation completed",
                    ))
                print(f"[ROS2Bridge Mock] Reached destination {target} (REACHED)!")
            except asyncio.CancelledError:
                if action_context:
                    self.session_manager.record_action_outcome(DirectActionOutcome(
                        **action_context, outcome="canceled", ros_status=5, error_code=1,
                        error_msg="Mock navigation canceled"
                    ))
                print("[ROS2Bridge Mock] Navigation simulation cancelled.")

        self._sim_task = asyncio.run_coroutine_threadsafe(_run_sim(), self.loop)

    def shutdown(self):
        if self._sim_task and not self._sim_task.done():
            self._sim_task.cancel()
        self._cancel_subtitle_timer()
