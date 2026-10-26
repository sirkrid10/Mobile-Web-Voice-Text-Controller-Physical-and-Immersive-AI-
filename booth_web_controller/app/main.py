"""FastAPI Application Entry Point.
Provides REST Endpoints, WebSocket /ws/status manager, Lifespan context,
and static file serving for Mobile Web Voice & Text Controller.
"""

import os
import json
import asyncio
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import (
    FastAPI, WebSocket, WebSocketDisconnect, Header, HTTPException,
    UploadFile, File, Depends, Form
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models import (
    ClaimSessionRequest, ClaimSessionResponse,
    HeartbeatResponse, DisconnectResponse,
    TextCommandRequest, CommandResponse,
    StaffConfigUpdate, StaffConfigSnapshot, StaffMockEvent,
    StateBroadcast
)
from app.session_manager import session_manager
from app.stt_service import STTUnavailableError, stt_service
from app.ros2_bridge import create_ros2_bridge, BaseROS2Bridge


# ---------------------------------------------------------------------------
# WebSocket Connection Manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        async with self._lock:
            self.active_connections.append(websocket)
        # Send immediate initial state
        state = session_manager.get_state_broadcast()
        await websocket.send_text(state.model_dump_json())

    async def disconnect(self, websocket: WebSocket):
        async with self._lock:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)

    async def broadcast_state(self):
        state = session_manager.get_state_broadcast()
        payload = state.model_dump_json()
        async with self._lock:
            disconnected = []
            for ws in self.active_connections:
                try:
                    await ws.send_text(payload)
                except Exception:
                    disconnected.append(ws)
            for ws in disconnected:
                if ws in self.active_connections:
                    self.active_connections.remove(ws)


ws_manager = ConnectionManager()
ros_bridge_instance: Optional[BaseROS2Bridge] = None
watchdog_task: Optional[asyncio.Task] = None


# ---------------------------------------------------------------------------
# Background Watchdog Loop
# ---------------------------------------------------------------------------

async def session_watchdog_loop():
    print("[Main] Session Watchdog Loop started (1.0s interval).")
    try:
        while True:
            await asyncio.sleep(1.0)
            await session_manager.watchdog_tick()
            await ws_manager.broadcast_state()
    except asyncio.CancelledError:
        print("[Main] Session Watchdog Loop cancelled.")


# ---------------------------------------------------------------------------
# Application Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    global ros_bridge_instance, watchdog_task
    loop = asyncio.get_running_loop()

    # 1. Initialize ROS 2 Bridge (Real or Mock)
    ros_bridge_instance = create_ros2_bridge(session_manager, loop)
    session_manager.set_ros_bridge(ros_bridge_instance)
    session_manager.set_broadcast_callback(ws_manager.broadcast_state)

    # 2. Start Background Watchdog
    watchdog_task = asyncio.create_task(session_watchdog_loop())

    yield

    # Teardown
    if watchdog_task and not watchdog_task.done():
        watchdog_task.cancel()
    if ros_bridge_instance:
        ros_bridge_instance.shutdown()
    print("[Main] Shutdown complete.")


app = FastAPI(
    title="Mobile Web Voice & Text Controller",
    description="Physical & Immersive AI: TurtleBot3 + ROS 2 Nav2 + LLM + VR Mind View",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Security Helpers
# ---------------------------------------------------------------------------

def verify_staff_pin(x_staff_pin: Optional[str] = Header(None, alias="X-Staff-Pin")):
    if not x_staff_pin or x_staff_pin != settings.STAFF_PIN:
        raise HTTPException(status_code=401, detail="Invalid Staff PIN")
    return True


# ---------------------------------------------------------------------------
# Frontend Page Routes
# ---------------------------------------------------------------------------

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")

@app.get("/", summary="Visitor Mobile Controller View")
async def get_index():
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "index.html not found"}


@app.get("/staff", summary="Staff Override & Recovery Panel")
async def get_staff():
    staff_file = os.path.join(STATIC_DIR, "staff.html")
    if os.path.exists(staff_file):
        return FileResponse(staff_file)
    return {"message": "staff.html not found"}


# ---------------------------------------------------------------------------
# REST API: State & Visitor Session
# ---------------------------------------------------------------------------

@app.get("/api/v1/state", response_model=StateBroadcast, summary="Get full system state snapshot")
async def get_state():
    return session_manager.get_state_broadcast()


@app.post("/api/v1/session/claim", response_model=ClaimSessionResponse, summary="Claim exclusive session lock")
async def claim_session(req: ClaimSessionRequest):
    return await session_manager.claim(req.session_id)


@app.post("/api/v1/session/heartbeat", response_model=HeartbeatResponse, summary="Extend session timeout (Still here)")
async def heartbeat_session(x_session_token: Optional[str] = Header(None, alias="X-Session-Token")):
    if not x_session_token:
        raise HTTPException(status_code=400, detail="Missing X-Session-Token header")
    result = await session_manager.heartbeat(x_session_token)
    await ws_manager.broadcast_state()
    return result


@app.post("/api/v1/session/disconnect", response_model=DisconnectResponse, summary="Release session & trigger auto-return")
async def disconnect_session(x_session_token: Optional[str] = Header(None, alias="X-Session-Token")):
    if not x_session_token or x_session_token != session_manager.active_session_token:
        raise HTTPException(status_code=403, detail="Invalid session token for active controller")
    auto_return_scheduled = await session_manager.release_session(reason="user_disconnect")
    await ws_manager.broadcast_state()
    return {"status": "disconnected", "auto_return_scheduled": auto_return_scheduled}


# ---------------------------------------------------------------------------
# REST API: Commands (Voice & Text)
# ---------------------------------------------------------------------------

@app.post("/api/v1/command/voice", response_model=CommandResponse, summary="Submit voice recording (WebM/MP4)")
async def command_voice(
    audio: UploadFile = File(...),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id")
):
    if not x_session_id:
        raise HTTPException(status_code=400, detail="Missing X-Session-Id header")

    # Validate claim or auto-claim
    validated_token = await session_manager.validate_or_auto_claim(x_session_id, x_session_token)

    # Transcribe speech
    try:
        transcript = await stt_service.transcribe_audio(audio)
    except STTUnavailableError as exc:
        raise HTTPException(status_code=503, detail="ระบบแปลงเสียงไม่พร้อมใช้งาน กรุณาลองใหม่ภายหลัง") from exc
    if not transcript or not transcript.strip():
        raise HTTPException(status_code=422, detail="ไม่พบข้อความจากเสียง")
    transcript = transcript.strip()

    request_id, registered_session_id = await session_manager.begin_user_request(x_session_id, validated_token)

    # Publish to ROS 2
    if ros_bridge_instance:
        try:
            ros_bridge_instance.publish_user_transcript(
                request_id=request_id,
                session_id=registered_session_id,
                input_mode="voice",
                text=transcript
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Unable to publish command: {exc}") from exc

    await ws_manager.broadcast_state()
    return {
        "status": "sent",
        "transcript": transcript,
        "inactivity_remaining_sec": session_manager.get_remaining_sec(),
        "request_id": request_id,
        "session_id": registered_session_id,
        "session_token": validated_token
    }


@app.post("/api/v1/command/text", response_model=CommandResponse, summary="Submit text or quick chip command")
async def command_text(
    req: TextCommandRequest,
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id")
):
    if not x_session_id:
        raise HTTPException(status_code=400, detail="Missing X-Session-Id header")

    # Validate claim or auto-claim
    validated_token = await session_manager.validate_or_auto_claim(x_session_id, x_session_token)
    request_id, registered_session_id = await session_manager.begin_user_request(x_session_id, validated_token)

    # Publish to ROS 2
    if ros_bridge_instance:
        try:
            ros_bridge_instance.publish_user_transcript(
                request_id=request_id,
                session_id=registered_session_id,
                input_mode=req.input_mode,
                text=req.text
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Unable to publish command: {exc}") from exc

    await ws_manager.broadcast_state()
    return {
        "status": "sent",
        "transcript": req.text,
        "inactivity_remaining_sec": session_manager.get_remaining_sec(),
        "request_id": request_id,
        "session_id": registered_session_id,
        "session_token": validated_token
    }


# ---------------------------------------------------------------------------
# REST API: Staff Controls & Overrides
# ---------------------------------------------------------------------------

@app.post("/api/v1/staff/emergency-stop", summary="Emergency Stop TurtleBot3 immediately")
async def staff_emergency_stop(_: bool = Depends(verify_staff_pin)):
    await session_manager.emergency_stop()
    return {"status": "stopped"}


@app.post("/api/v1/staff/return-to-start", summary="Manually command robot to return to Start Booth")
async def staff_return_to_start(_: bool = Depends(verify_staff_pin)):
    await session_manager.return_to_start_now()
    return {"status": "returning", "target": settings.START_BOOTH_ID}


@app.post("/api/v1/staff/config", summary="Update runtime auto-return and timeout settings")
async def staff_update_config(req: StaffConfigUpdate, _: bool = Depends(verify_staff_pin)):
    await session_manager.update_staff_config(
        auto_return_enabled=req.auto_return_enabled,
        inactivity_timeout_sec=req.inactivity_timeout_sec,
        auto_return_delay_sec=req.auto_return_delay_sec
    )
    return {
        "status": "updated",
        "auto_return_enabled": session_manager.auto_return_enabled,
        "inactivity_timeout_sec": session_manager.inactivity_timeout_sec,
        "auto_return_delay_sec": session_manager.auto_return_delay_sec
    }


@app.get("/api/v1/staff/config", response_model=StaffConfigSnapshot,
         summary="Read staff settings after PIN verification")
async def staff_read_config(_: bool = Depends(verify_staff_pin)):
    return StaffConfigSnapshot(
        auto_return_enabled=session_manager.auto_return_enabled,
        inactivity_timeout_sec=session_manager.inactivity_timeout_sec,
        auto_return_delay_sec=session_manager.auto_return_delay_sec,
    )


@app.post("/api/v1/staff/force-release", summary="Force unlock active session lock")
async def staff_force_release(_: bool = Depends(verify_staff_pin)):
    await session_manager.force_release()
    return {"status": "released"}


@app.post("/api/v1/staff/mock-event", summary="Simulate ROS 2 perception and robot navigation state")
async def staff_mock_event(req: StaffMockEvent, _: bool = Depends(verify_staff_pin)):
    if ros_bridge_instance:
        ros_bridge_instance.inject_system_state(
            state=req.state,
            goal=req.goal,
            obstacle_detected=req.obstacle_detected,
            pose=req.pose
        )
    else:
        session_manager.update_from_ros_state(
            state=req.state,
            goal=req.goal,
            obstacle_detected=req.obstacle_detected,
            pose=req.pose
        )
    await ws_manager.broadcast_state()
    return {"status": "simulated"}


# ---------------------------------------------------------------------------
# WebSocket Endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep receiving pings / client messages
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
    except Exception:
        await ws_manager.disconnect(websocket)


# Mount static assets directory
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
