"""HTTP adapters for sessions operations."""

from typing import Optional

from fastapi import Header, HTTPException, APIRouter
from fastapi.responses import JSONResponse

from app import runtime
from app.models import (
    ClaimSessionRequest,
    ClaimSessionResponse,
    HeartbeatResponse,
    DisconnectResponse,
    StateBroadcast,
)


router = APIRouter()


@router.get("/api/v1/health")
async def service_health():
    return JSONResponse({"service": "mobile-web-voice-text-controller", "instance_id": runtime.INSTANCE_ID},
                        headers={"Cache-Control": "no-store"})


@router.get("/api/v1/state", response_model=StateBroadcast, summary="Get full system state snapshot")
async def get_state():
    return runtime.session_manager.get_state_broadcast()


@router.post("/api/v1/session/claim", response_model=ClaimSessionResponse, summary="Claim exclusive session lock")
async def claim_session(req: ClaimSessionRequest):
    return await runtime.session_manager.claim(req.session_id)


@router.post("/api/v1/session/heartbeat", response_model=HeartbeatResponse, summary="Extend session timeout (Still here)")
async def heartbeat_session(x_session_token: Optional[str] = Header(None, alias="X-Session-Token")):
    if not x_session_token:
        raise HTTPException(status_code=400, detail="Missing X-Session-Token header")
    result = await runtime.session_manager.heartbeat(x_session_token)
    await runtime.ws_manager.broadcast_state()
    return result


@router.post("/api/v1/session/disconnect", response_model=DisconnectResponse, summary="Release session & trigger auto-return")
async def disconnect_session(x_session_token: Optional[str] = Header(None, alias="X-Session-Token")):
    if not x_session_token or x_session_token != runtime.session_manager.identity.active_session_token:
        raise HTTPException(status_code=403, detail="Invalid session token for active controller")
    auto_return_scheduled = await runtime.session_manager.release_session(reason="user_disconnect")
    await runtime.ws_manager.broadcast_state()
    return {"status": "disconnected", "auto_return_scheduled": auto_return_scheduled}
