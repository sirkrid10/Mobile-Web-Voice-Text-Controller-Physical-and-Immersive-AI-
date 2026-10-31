"""Group mutable state by session, display and request lifetimes."""

from dataclasses import dataclass, field

from app.models import IntentOutcome, IntentDispatchOutcome, DirectActionOutcome


class SessionError(Exception):
    """A rejected session operation, translated by the HTTP adapter."""

    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


@dataclass
class SessionIdentity:
    active_session_id: str | None = None
    active_session_token: str | None = None
    last_activity_ts: float = 0.0


@dataclass
class RobotDisplay:
    robot_state: str = 'IDLE'
    current_goal: str | None = None
    heard_text: str = ''
    llm_explanation: str = 'พร้อมรับคำสั่งจากผู้เข้าชมบูธ'
    obstacle_detected: bool = False
    robot_pose: dict[str, float] = field(default_factory=lambda: {'x': 0.0, 'y': 0.0})


@dataclass
class RequestHistory:
    latest_request_identity: tuple[str, str] | None = None
    latest_intent: IntentOutcome | None = None
    latest_intent_dispatch: IntentDispatchOutcome | None = None
    latest_action: DirectActionOutcome | None = None
