"""Pydantic schemas and models for REST API requests/responses and WebSocket broadcasts.
"""

from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Session Models
# ---------------------------------------------------------------------------

class ClaimSessionRequest(BaseModel):
    session_id: str = Field(..., description="Unique client identifier (UUID or persistent device ID)")


class ClaimSessionResponse(BaseModel):
    status: Literal["claimed"] = "claimed"
    session_id: str
    session_token: str
    inactivity_remaining_sec: int


class HeartbeatResponse(BaseModel):
    status: Literal["extended"] = "extended"
    inactivity_remaining_sec: int


class DisconnectResponse(BaseModel):
    status: Literal["disconnected"] = "disconnected"
    auto_return_scheduled: bool


# ---------------------------------------------------------------------------
# Command Models
# ---------------------------------------------------------------------------

class TextCommandRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500, description="Natural language command or prompt")
    input_mode: Literal["text", "chip"] = "text"


class CommandResponse(BaseModel):
    status: Literal["sent"] = "sent"
    transcript: str
    inactivity_remaining_sec: int
    session_token: Optional[str] = None


# ---------------------------------------------------------------------------
# Staff Models
# ---------------------------------------------------------------------------

class StaffConfigUpdate(BaseModel):
    auto_return_enabled: Optional[bool] = None
    inactivity_timeout_sec: Optional[int] = Field(None, ge=10, le=600)
    auto_return_delay_sec: Optional[int] = Field(None, ge=1, le=120)


class StaffMockEvent(BaseModel):
    state: Literal["IDLE", "NAVIGATING", "REPLANNING", "REACHED", "STOPPED", "FAILED"]
    goal: Optional[str] = None
    obstacle_detected: bool = False
    pose: Optional[Dict[str, float]] = None


# ---------------------------------------------------------------------------
# Robot & System State
# ---------------------------------------------------------------------------

class StateBroadcast(BaseModel):
    robot_state: Literal["IDLE", "NAVIGATING", "REPLANNING", "REACHED", "STOPPED", "FAILED"]
    heard_text: str
    current_goal: Optional[str]
    llm_reason: str
    is_busy: bool
    lock_status: Literal["AVAILABLE", "LOCKED"]
    active_session_id: Optional[str]
    inactivity_remaining_sec: int
    timer_paused_for_navigation: bool
    show_timeout_warning: bool
    auto_return_enabled: bool
    auto_return_delay_sec: int
    obstacle_detected: bool
    locations: List[Dict[str, Any]]
