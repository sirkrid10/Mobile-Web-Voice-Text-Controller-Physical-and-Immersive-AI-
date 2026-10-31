"""Exclusive Session Manager & Smart Watchdog State Machine.
Manages single-device session locking, configurable inactivity timing with navigation pause,
and automatic return to Start Booth upon session termination.
"""

import time
import secrets
import asyncio
from typing import Optional, Dict, Any, Callable
from app.session_state import SessionError, SessionIdentity, RobotDisplay, RequestHistory
from app.auto_return import AutoReturn
from app.bridge_base import BaseROS2Bridge

from app.config import settings
from app.models import DirectActionOutcome, IntentDispatchOutcome, IntentOutcome, StateBroadcast


class SessionManager:
    def __init__(self):
        self.identity = SessionIdentity()
        self.display = RobotDisplay(current_goal=settings.START_BOOTH_ID)
        self.requests = RequestHistory()
        self.auto_return = AutoReturn()

        # Timing configurations
        self.inactivity_timeout_sec: int = settings.INACTIVITY_TIMEOUT_SEC
        self.warning_threshold_sec: int = settings.WARNING_THRESHOLD_SEC
        self.auto_return_enabled: bool = settings.AUTO_RETURN_ENABLED
        self.auto_return_delay_sec: int = settings.AUTO_RETURN_DELAY_SEC

        # External hooks
        self.ros_bridge: Optional[BaseROS2Bridge] = None
        self.broadcast_callback: Optional[Callable[[], None]] = None
        self.history_callback = None
        self._lock = asyncio.Lock()


    def set_history_callback(self, callback):
        self.history_callback = callback

    def _record_history(self, kind, result):
        if self.history_callback:
            try:
                self.history_callback(kind, text=getattr(result, 'message', ''), **result.model_dump())
            except Exception:
                pass

    def set_ros_bridge(self, bridge: BaseROS2Bridge | None):
        self.ros_bridge = bridge

    def set_broadcast_callback(self, cb: Callable[[], None]):
        self.broadcast_callback = cb

    def _trigger_broadcast(self):
        if self.broadcast_callback:
            try:
                res = self.broadcast_callback()
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception as e:
                print(f"[SessionManager] Broadcast trigger error: {e}")

    # -----------------------------------------------------------------------
    # Rule 1 — Claiming a Session
    # -----------------------------------------------------------------------
    async def claim(self, session_id: str) -> Dict[str, Any]:
        async with self._lock:
            # Case A: System is currently free
            if self.identity.active_session_id is None:
                self.identity.active_session_id = session_id
                self.identity.active_session_token = secrets.token_hex(16)
                self.identity.last_activity_ts = time.time()
                self.requests.latest_request_identity = None
                self.requests.latest_intent = None
                self.requests.latest_intent_dispatch = None

                # Cancel any pending auto-return task since a new visitor arrived
                if self.auto_return.cancel_pending():
                    print(f"[SessionManager] Cancelled auto-return task. New session claimed by {session_id}")

                self._trigger_broadcast()
                return {
                    "status": "claimed",
                    "session_id": session_id,
                    "session_token": self.identity.active_session_token,
                    "inactivity_remaining_sec": self.inactivity_timeout_sec
                }

            # Case B: The same visitor re-claiming / refreshing their session
            if self.identity.active_session_id == session_id:
                self.identity.last_activity_ts = time.time()
                return {
                    "status": "claimed",
                    "session_id": session_id,
                    "session_token": self.identity.active_session_token,
                    "inactivity_remaining_sec": self.get_remaining_sec()
                }

            # Case C: Locked by another visitor
            raise SessionError(
                status_code=409,
                detail="Session locked by another visitor. Please wait for current session to finish."
            )

    # -----------------------------------------------------------------------
    # Rule 2 — Command Validation & Auto-Claim on First Interaction
    # -----------------------------------------------------------------------
    async def validate_or_auto_claim(self, session_id: str, session_token: Optional[str]) -> str:
        async with self._lock:
            # Auto-claim if available
            if self.identity.active_session_id is None:
                self.identity.active_session_id = session_id
                self.identity.active_session_token = secrets.token_hex(16)
                self.identity.last_activity_ts = time.time()
                self.requests.latest_request_identity = None
                self.requests.latest_intent = None
                self.requests.latest_intent_dispatch = None
                self.auto_return.cancel_pending()
                self._trigger_broadcast()
                return self.identity.active_session_token

            # Existing claim verification
            if self.identity.active_session_id == session_id:
                if session_token and session_token == self.identity.active_session_token:
                    self.identity.last_activity_ts = time.time()
                    return self.identity.active_session_token
                raise SessionError(status_code=403, detail="Invalid session token for active controller.")

            raise SessionError(status_code=403, detail="Robot is currently controlled by another visitor.")

    async def begin_user_request(self, session_id: str, expected_token: str) -> tuple[str, str]:
        """Register a command before publishing so immediate ROS results can correlate."""
        async with self._lock:
            if self.identity.active_session_id != session_id or self.identity.active_session_token != expected_token:
                raise SessionError(status_code=403, detail="Session ownership changed before command submission.")
            identity = (f"req-{secrets.token_hex(8)}", session_id)
            self.requests.latest_request_identity = identity
            self.requests.latest_intent = None
            self.requests.latest_intent_dispatch = None
            self._trigger_broadcast()
            return identity

    def record_intent_result(self, result: IntentOutcome) -> bool:
        """Accept one result only for the current visitor request."""
        if self.requests.latest_request_identity != (result.request_id, result.session_id):
            return False
        if self.identity.active_session_id != result.session_id:
            return False
        if self.requests.latest_intent and self.requests.latest_intent.request_id == result.request_id:
            return False
        self.requests.latest_intent = result
        self._record_history('intent', result)
        self._trigger_broadcast()
        return True

    def record_action_outcome(self, result: DirectActionOutcome) -> bool:
        """Update the snapshot only for the newest backend-owned Action."""
        if self.requests.latest_action and self.requests.latest_action.request_id != result.request_id:
            if result.outcome != "sending":
                return False
        terminal = {"unavailable", "rejected", "succeeded", "aborted", "canceled", "failed", "transport_error"}
        if (
            self.requests.latest_action
            and self.requests.latest_action.request_id == result.request_id
            and self.requests.latest_action.outcome in terminal
        ):
            return False
        self.requests.latest_action = result
        self._trigger_broadcast()
        return True

    def record_intent_dispatch(self, result: IntentDispatchOutcome) -> bool:
        """Correlate sender evidence even when it arrives before IntentResult."""
        if self.requests.latest_request_identity != (result.request_id, result.session_id):
            return False
        if self.identity.active_session_id != result.session_id or self.requests.latest_intent_dispatch is not None:
            return False
        self.requests.latest_intent_dispatch = result
        self._record_history('dispatch', result)
        self._trigger_broadcast()
        return True

    # -----------------------------------------------------------------------
    # Heartbeat (Extend Session Time)
    # -----------------------------------------------------------------------
    async def heartbeat(self, session_token: str) -> Dict[str, Any]:
        async with self._lock:
            if not self.identity.active_session_token or session_token != self.identity.active_session_token:
                raise SessionError(status_code=403, detail="Invalid or expired session token.")

            self.identity.last_activity_ts = time.time()
            return {
                "status": "extended",
                "inactivity_remaining_sec": self.inactivity_timeout_sec
            }

    # -----------------------------------------------------------------------
    # Rule 3 — Smart Watchdog Tick (Called every 1.0s)
    # -----------------------------------------------------------------------
    async def watchdog_tick(self) -> StateBroadcast:
        async with self._lock:
            is_navigating = self.display.robot_state in ("NAVIGATING", "REPLANNING")

            if self.identity.active_session_id is not None:
                if is_navigating:
                    # Smart Timer Pause: keep timer reset while robot is traveling!
                    self.identity.last_activity_ts = time.time()
                    remaining = self.inactivity_timeout_sec
                    show_warning = False
                    timer_paused = True
                else:
                    # Stationary countdown: robot is IDLE, REACHED, STOPPED, or FAILED
                    timer_paused = False
                    elapsed = int(time.time() - self.identity.last_activity_ts)
                    remaining = max(0, self.inactivity_timeout_sec - elapsed)
                    show_warning = (0 < remaining <= self.warning_threshold_sec)

                    if remaining == 0:
                        print(f"[SessionManager] Inactivity timeout reached for session {self.identity.active_session_id}")
                        asyncio.create_task(self.release_session(reason="inactivity_timeout"))
            else:
                remaining = self.inactivity_timeout_sec
                show_warning = False
                timer_paused = False

            return self._build_state_broadcast(remaining, timer_paused, show_warning)

    def get_remaining_sec(self) -> int:
        if not self.identity.active_session_id:
            return self.inactivity_timeout_sec
        if self.display.robot_state in ("NAVIGATING", "REPLANNING"):
            return self.inactivity_timeout_sec
        elapsed = int(time.time() - self.identity.last_activity_ts)
        return max(0, self.inactivity_timeout_sec - elapsed)

    # -----------------------------------------------------------------------
    # Rule 4 — Releasing Session & Auto-Return Task
    # -----------------------------------------------------------------------
    async def release_session(self, reason: str = "user_disconnect") -> bool:
        async with self._lock:
            if self.identity.active_session_id is None:
                return False

            released_session = self.identity.active_session_id
            self.identity.active_session_id = None
            self.identity.active_session_token = None
            self.requests.latest_request_identity = None
            self.requests.latest_intent = None
            self.requests.latest_intent_dispatch = None
            print(f"[SessionManager] Released session {released_session} (reason: {reason})")

            # Check Auto-Return criteria
            should_auto_return = self.auto_return.eligible(
                self.auto_return_enabled, reason, self.display.current_goal,
            )

            if should_auto_return:
                self.auto_return.schedule(self)
                print(f"[SessionManager] Scheduled Auto-Return in {self.auto_return_delay_sec}s")

            self._trigger_broadcast()
            return should_auto_return

    # -----------------------------------------------------------------------
    # Staff Controls & Overrides
    # -----------------------------------------------------------------------
    async def force_release(self):
        return await self.release_session(reason="staff_force_release")

    async def emergency_stop(self):
        async with self._lock:
            self.display.robot_state = "STOPPED"
            self.display.llm_explanation = "🚨 สตาฟกดหยุดฉุกเฉิน (Emergency Stop)"
            if self.ros_bridge:
                self.ros_bridge.publish_emergency_stop()
        self._trigger_broadcast()

    async def return_to_start_now(self):
        async with self._lock:
            self.display.current_goal = settings.START_BOOTH_ID
            self.display.heard_text = "คำสั่งสตาฟ: กลับจุดเริ่มต้นทันที"
            self.display.llm_explanation = "สตาฟสั่งให้หุ่นยนต์กลับจุดเริ่มต้นหน้าร้านทันที"
            if self.ros_bridge:
                self.ros_bridge.publish_high_level_action(
                    action="GO_TO",
                    target=settings.START_BOOTH_ID,
                    explanation="Staff triggered Return to Start Booth immediately",
                    source="staff_override"
                )
        self._trigger_broadcast()

    async def update_staff_config(self, auto_return_enabled: Optional[bool],
                                  inactivity_timeout_sec: Optional[int],
                                  auto_return_delay_sec: Optional[int]):
        async with self._lock:
            if auto_return_enabled is not None:
                self.auto_return_enabled = auto_return_enabled
            if inactivity_timeout_sec is not None:
                self.inactivity_timeout_sec = inactivity_timeout_sec
            if auto_return_delay_sec is not None:
                self.auto_return_delay_sec = auto_return_delay_sec
        self._trigger_broadcast()

    # -----------------------------------------------------------------------
    # ROS 2 Callbacks Integration
    # -----------------------------------------------------------------------
    def update_from_ros_state(self, state: str, goal: Optional[str] = None,
                              obstacle_detected: bool = False,
                              pose: Optional[Dict[str, float]] = None):
        self.display.robot_state = state
        if goal:
            self.display.current_goal = goal
        self.display.obstacle_detected = obstacle_detected
        if pose:
            self.display.robot_pose = pose
        self._trigger_broadcast()

    def update_from_llm_mind(self, heard_text: str, target: Optional[str] = None,
                             explanation: Optional[str] = None):
        if heard_text:
            self.display.heard_text = heard_text
        if target:
            self.display.current_goal = target
        if explanation:
            self.display.llm_explanation = explanation
        self._trigger_broadcast()

    # -----------------------------------------------------------------------
    # State Snapshot Serialization
    # -----------------------------------------------------------------------
    def get_state_broadcast(self) -> StateBroadcast:
        is_navigating = self.display.robot_state in ("NAVIGATING", "REPLANNING")
        remaining = self.get_remaining_sec()
        show_warning = (self.identity.active_session_id is not None and not is_navigating and 0 < remaining <= self.warning_threshold_sec)
        return self._build_state_broadcast(remaining, is_navigating, show_warning)

    def _build_state_broadcast(self, remaining: int, timer_paused: bool, show_warning: bool) -> StateBroadcast:
        return StateBroadcast(
            robot_state=self.display.robot_state,
            heard_text=self.display.heard_text,
            current_goal=self.display.current_goal,
            llm_reason=self.display.llm_explanation,
            is_busy=(self.display.robot_state in ("NAVIGATING", "REPLANNING")),
            lock_status="AVAILABLE" if self.identity.active_session_id is None else "LOCKED",
            active_session_id=self.identity.active_session_id,
            inactivity_remaining_sec=remaining,
            timer_paused_for_navigation=timer_paused,
            show_timeout_warning=show_warning,
            auto_return_enabled=self.auto_return_enabled,
            auto_return_delay_sec=self.auto_return_delay_sec,
            obstacle_detected=self.display.obstacle_detected,
            locations=settings.LOCATIONS,
            latest_intent=self.requests.latest_intent,
            latest_request_id=self.requests.latest_request_identity[0] if self.requests.latest_request_identity else None,
            latest_intent_dispatch=self.requests.latest_intent_dispatch,
            latest_action=self.requests.latest_action
        )


session_manager = SessionManager()
