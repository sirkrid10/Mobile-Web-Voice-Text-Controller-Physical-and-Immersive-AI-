"""Exclusive Session Manager & Smart Watchdog State Machine.
Manages single-device session locking, smart 60s inactivity timer with navigation pause,
and automatic return to Start Booth upon session termination.
"""

import time
import secrets
import asyncio
from typing import Optional, Dict, Any, Callable
from fastapi import HTTPException

from app.config import settings
from app.models import StateBroadcast


class SessionManager:
    def __init__(self):
        self.active_session_id: Optional[str] = None
        self.active_session_token: Optional[str] = None
        self.last_activity_ts: float = 0.0

        # Timing configurations
        self.inactivity_timeout_sec: int = settings.INACTIVITY_TIMEOUT_SEC
        self.warning_threshold_sec: int = settings.WARNING_THRESHOLD_SEC
        self.auto_return_enabled: bool = settings.AUTO_RETURN_ENABLED
        self.auto_return_delay_sec: int = settings.AUTO_RETURN_DELAY_SEC

        # Auto-return background task
        self.auto_return_task: Optional[asyncio.Task] = None

        # Robot & Brain Live State
        self.robot_state: str = "IDLE"  # IDLE, NAVIGATING, REPLANNING, REACHED, STOPPED, FAILED
        self.current_goal: Optional[str] = settings.START_BOOTH_ID
        self.heard_text: str = ""
        self.llm_explanation: str = "?????????????????????????????"
        self.obstacle_detected: bool = False
        self.robot_pose: Dict[str, float] = {"x": 0.0, "y": 0.0}

        # External hooks
        self.ros_bridge: Optional[Any] = None
        self.broadcast_callback: Optional[Callable[[], None]] = None
        self._lock = asyncio.Lock()

    def set_ros_bridge(self, bridge: Any):
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
    # Rule 1 ? Claiming a Session
    # -----------------------------------------------------------------------
    async def claim(self, session_id: str) -> Dict[str, Any]:
        async with self._lock:
            # Case A: System is currently free
            if self.active_session_id is None:
                self.active_session_id = session_id
                self.active_session_token = secrets.token_hex(16)
                self.last_activity_ts = time.time()

                # Cancel any pending auto-return task since a new visitor arrived
                if self.auto_return_task and not self.auto_return_task.done():
                    self.auto_return_task.cancel()
                    self.auto_return_task = None
                    print(f"[SessionManager] Cancelled auto-return task. New session claimed by {session_id}")

                self._trigger_broadcast()
                return {
                    "status": "claimed",
                    "session_id": session_id,
                    "session_token": self.active_session_token,
                    "inactivity_remaining_sec": self.inactivity_timeout_sec
                }

            # Case B: The same visitor re-claiming / refreshing their session
            if self.active_session_id == session_id:
                self.last_activity_ts = time.time()
                return {
                    "status": "claimed",
                    "session_id": session_id,
                    "session_token": self.active_session_token,
                    "inactivity_remaining_sec": self.get_remaining_sec()
                }

            # Case C: Locked by another visitor
            raise HTTPException(
                status_code=409,
                detail="Session locked by another visitor. Please wait for current session to finish."
            )

    # -----------------------------------------------------------------------
    # Rule 2 ? Command Validation & Auto-Claim on First Interaction
    # -----------------------------------------------------------------------
    async def validate_or_auto_claim(self, session_id: str, session_token: Optional[str]) -> str:
        async with self._lock:
            # Auto-claim if available
            if self.active_session_id is None:
                self.active_session_id = session_id
                self.active_session_token = secrets.token_hex(16)
                self.last_activity_ts = time.time()
                if self.auto_return_task and not self.auto_return_task.done():
                    self.auto_return_task.cancel()
                    self.auto_return_task = None
                self._trigger_broadcast()
                return self.active_session_token

            # Existing claim verification
            if self.active_session_id == session_id:
                if session_token and session_token == self.active_session_token:
                    self.last_activity_ts = time.time()
                    return self.active_session_token
                raise HTTPException(status_code=403, detail="Invalid session token for active controller.")

            raise HTTPException(status_code=403, detail="Robot is currently controlled by another visitor.")

    # -----------------------------------------------------------------------
    # Heartbeat (Extend Session Time)
    # -----------------------------------------------------------------------
    async def heartbeat(self, session_token: str) -> Dict[str, Any]:
        async with self._lock:
            if not self.active_session_token or session_token != self.active_session_token:
                raise HTTPException(status_code=403, detail="Invalid or expired session token.")

            self.last_activity_ts = time.time()
            return {
                "status": "extended",
                "inactivity_remaining_sec": self.inactivity_timeout_sec
            }

    # -----------------------------------------------------------------------
    # Rule 3 ? Smart Watchdog Tick (Called every 1.0s)
    # -----------------------------------------------------------------------
    async def watchdog_tick(self) -> StateBroadcast:
        async with self._lock:
            is_navigating = self.robot_state in ("NAVIGATING", "REPLANNING")

            if self.active_session_id is not None:
                if is_navigating:
                    # Smart Timer Pause: keep timer reset while robot is traveling!
                    self.last_activity_ts = time.time()
                    remaining = self.inactivity_timeout_sec
                    show_warning = False
                    timer_paused = True
                else:
                    # Stationary countdown: robot is IDLE, REACHED, STOPPED, or FAILED
                    timer_paused = False
                    elapsed = int(time.time() - self.last_activity_ts)
                    remaining = max(0, self.inactivity_timeout_sec - elapsed)
                    show_warning = (0 < remaining <= self.warning_threshold_sec)

                    if remaining == 0:
                        print(f"[SessionManager] Inactivity timeout reached for session {self.active_session_id}")
                        # Release session asynchronously outside this lock block
                        asyncio.create_task(self.release_session(reason="inactivity_timeout"))
            else:
                remaining = self.inactivity_timeout_sec
                show_warning = False
                timer_paused = False

            return self._build_state_broadcast(remaining, timer_paused, show_warning)

    def get_remaining_sec(self) -> int:
        if not self.active_session_id:
            return self.inactivity_timeout_sec
        if self.robot_state in ("NAVIGATING", "REPLANNING"):
            return self.inactivity_timeout_sec
        elapsed = int(time.time() - self.last_activity_ts)
        return max(0, self.inactivity_timeout_sec - elapsed)

    # -----------------------------------------------------------------------
    # Rule 4 ? Releasing Session & Auto-Return Task
    # -----------------------------------------------------------------------
    async def release_session(self, reason: str = "user_disconnect") -> bool:
        async with self._lock:
            if self.active_session_id is None:
                return False

            released_session = self.active_session_id
            self.active_session_id = None
            self.active_session_token = None
            print(f"[SessionManager] Released session {released_session} (reason: {reason})")

            # Check Auto-Return criteria
            should_auto_return = (
                self.auto_return_enabled and
                reason in ("user_disconnect", "inactivity_timeout") and
                self.current_goal != settings.START_BOOTH_ID
            )

            if should_auto_return:
                if self.auto_return_task and not self.auto_return_task.done():
                    self.auto_return_task.cancel()
                self.auto_return_task = asyncio.create_task(self._delayed_auto_return())
                print(f"[SessionManager] Scheduled Auto-Return in {self.auto_return_delay_sec}s")

            self._trigger_broadcast()
            return should_auto_return

    async def _delayed_auto_return(self):
        try:
            print(f"[SessionManager] Auto-return waiting {self.auto_return_delay_sec}s grace period...")
            await asyncio.sleep(self.auto_return_delay_sec)

            async with self._lock:
                # Check if anyone has claimed the session in the meantime
                if self.active_session_id is not None:
                    print("[SessionManager] Auto-return aborted: new session was claimed.")
                    return

                print("[SessionManager] Executing Auto-Return to START_BOOTH...")
                self.current_goal = settings.START_BOOTH_ID
                self.heard_text = "??????????????? (Auto-Return)"
                self.llm_explanation = "?????????????? ??????????????????????????????????????????"

                if self.ros_bridge:
                    self.ros_bridge.publish_high_level_action(
                        action="GO_TO",
                        target=settings.START_BOOTH_ID,
                        explanation="Auto-returning to Start Booth after session ended",
                        source="auto_return"
                    )

            self._trigger_broadcast()
        except asyncio.CancelledError:
            print("[SessionManager] Delayed auto-return task was cancelled.")

    # -----------------------------------------------------------------------
    # Staff Controls & Overrides
    # -----------------------------------------------------------------------
    async def force_release(self):
        return await self.release_session(reason="staff_force_release")

    async def emergency_stop(self):
        async with self._lock:
            self.robot_state = "STOPPED"
            self.llm_explanation = "?? ????????????????? (Emergency Stop)"
            if self.ros_bridge:
                self.ros_bridge.publish_emergency_stop()
        self._trigger_broadcast()

    async def return_to_start_now(self):
        async with self._lock:
            self.current_goal = settings.START_BOOTH_ID
            self.heard_text = "??????????: ????????????????????"
            self.llm_explanation = "???????????????????????????????????????????????"
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
        self.robot_state = state
        if goal:
            self.current_goal = goal
        self.obstacle_detected = obstacle_detected
        if pose:
            self.robot_pose = pose
        self._trigger_broadcast()

    def update_from_llm_mind(self, heard_text: str, target: Optional[str] = None,
                             explanation: Optional[str] = None):
        if heard_text:
            self.heard_text = heard_text
        if target:
            self.current_goal = target
        if explanation:
            self.llm_explanation = explanation
        self._trigger_broadcast()

    # -----------------------------------------------------------------------
    # State Snapshot Serialization
    # -----------------------------------------------------------------------
    def get_state_broadcast(self) -> StateBroadcast:
        is_navigating = self.robot_state in ("NAVIGATING", "REPLANNING")
        remaining = self.get_remaining_sec()
        show_warning = (self.active_session_id is not None and not is_navigating and 0 < remaining <= self.warning_threshold_sec)
        return self._build_state_broadcast(remaining, is_navigating, show_warning)

    def _build_state_broadcast(self, remaining: int, timer_paused: bool, show_warning: bool) -> StateBroadcast:
        return StateBroadcast(
            robot_state=self.robot_state,
            heard_text=self.heard_text,
            current_goal=self.current_goal,
            llm_reason=self.llm_explanation,
            is_busy=(self.robot_state in ("NAVIGATING", "REPLANNING")),
            lock_status="AVAILABLE" if self.active_session_id is None else "LOCKED",
            active_session_id=self.active_session_id,
            inactivity_remaining_sec=remaining,
            timer_paused_for_navigation=timer_paused,
            show_timeout_warning=show_warning,
            auto_return_enabled=self.auto_return_enabled,
            auto_return_delay_sec=self.auto_return_delay_sec,
            obstacle_detected=self.obstacle_detected,
            locations=settings.LOCATIONS
        )


session_manager = SessionManager()
