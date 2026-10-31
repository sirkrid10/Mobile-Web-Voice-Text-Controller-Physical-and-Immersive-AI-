"""HTTP adapters for staff operations."""

from typing import Literal

from fastapi import HTTPException, Depends, Query, APIRouter
from fastapi.responses import JSONResponse

from app import runtime
from app.agent_processes import ProcessControlError
from app.config import settings
from app.models import (
    StaffConfigUpdate,
    StaffConfigSnapshot,
    StaffMockEvent,
    SubtitleModeUpdate,
    SubtitleModeSnapshot,
    AgentModeUpdate,
    AudioPreprocessingUpdate,
)
from app.security import verify_staff_pin, verify_subtitle_staff_pin
from app.subtitle_mode import SubtitleModeError


router = APIRouter()


@router.post("/api/v1/staff/emergency-stop", summary="Emergency Stop TurtleBot3 immediately")
async def staff_emergency_stop(_: bool = Depends(verify_staff_pin)):
    await runtime.session_manager.emergency_stop()
    return {"status": "stopped"}


@router.post("/api/v1/staff/return-to-start", summary="Manually command robot to return to Start Booth")
async def staff_return_to_start(_: bool = Depends(verify_staff_pin)):
    await runtime.session_manager.return_to_start_now()
    return {"status": "returning", "target": settings.START_BOOTH_ID}


@router.post("/api/v1/staff/config", summary="Update runtime auto-return and timeout settings")
async def staff_update_config(req: StaffConfigUpdate, _: bool = Depends(verify_staff_pin)):
    await runtime.session_manager.update_staff_config(
        auto_return_enabled=req.auto_return_enabled,
        inactivity_timeout_sec=req.inactivity_timeout_sec,
        auto_return_delay_sec=req.auto_return_delay_sec
    )
    return {
        "status": "updated",
        "auto_return_enabled": runtime.session_manager.auto_return_enabled,
        "inactivity_timeout_sec": runtime.session_manager.inactivity_timeout_sec,
        "auto_return_delay_sec": runtime.session_manager.auto_return_delay_sec
    }


@router.get("/api/v1/staff/config", response_model=StaffConfigSnapshot,
         summary="Read staff settings after PIN verification")
async def staff_read_config(_: bool = Depends(verify_staff_pin)):
    return StaffConfigSnapshot(
        auto_return_enabled=runtime.session_manager.auto_return_enabled,
        inactivity_timeout_sec=runtime.session_manager.inactivity_timeout_sec,
        auto_return_delay_sec=runtime.session_manager.auto_return_delay_sec,
    )


@router.get("/api/v1/staff/subtitle-mode", response_model=SubtitleModeSnapshot)
async def staff_read_subtitle_mode(_: bool = Depends(verify_subtitle_staff_pin)):
    if runtime.ros_bridge_instance is None:
        raise HTTPException(status_code=503, detail="ROS bridge is not running")
    try:
        return SubtitleModeSnapshot(mode=await runtime.ros_bridge_instance.read_subtitle_mode())
    except SubtitleModeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None


@router.post("/api/v1/staff/subtitle-mode", response_model=SubtitleModeSnapshot)
async def staff_set_subtitle_mode(req: SubtitleModeUpdate, _: bool = Depends(verify_subtitle_staff_pin)):
    if runtime.ros_bridge_instance is None:
        raise HTTPException(status_code=503, detail="ROS bridge is not running")
    try:
        return SubtitleModeSnapshot(mode=await runtime.ros_bridge_instance.set_subtitle_mode(req.mode))
    except SubtitleModeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None


@router.post("/api/v1/staff/force-release", summary="Force unlock active session lock")
async def staff_force_release(_: bool = Depends(verify_staff_pin)):
    await runtime.session_manager.force_release()
    return {"status": "released"}


@router.get('/api/v1/staff/system')
async def staff_system(_: bool = Depends(verify_subtitle_staff_pin)):
    if runtime.system_health is None:
        raise HTTPException(status_code=503, detail='System inspection is not running')
    return JSONResponse(runtime.system_health.snapshot(), headers={'Cache-Control': 'no-store'})


@router.get('/api/v1/staff/history')
async def staff_dialogue_history(limit: int = Query(50, ge=1, le=2000), _: bool = Depends(verify_subtitle_staff_pin)):
    if runtime.dialogue_history is None:
        raise HTTPException(status_code=503, detail='Dialogue history is not running')
    return JSONResponse(runtime.dialogue_history.snapshot(limit), headers={'Cache-Control': 'no-store'})


@router.post('/api/v1/staff/system/mode')
async def staff_agent_mode(req: AgentModeUpdate, _: bool = Depends(verify_subtitle_staff_pin)):
    if runtime.agent_processes is None:
        raise HTTPException(status_code=503, detail='Process manager is not running')
    try:
        await runtime.agent_processes.set_mode(req.mode)
    except ProcessControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return JSONResponse(runtime.system_health.snapshot(), headers={'Cache-Control': 'no-store'})


@router.post('/api/v1/staff/system/audio')
async def staff_audio_preprocessing(req: AudioPreprocessingUpdate, _: bool = Depends(verify_subtitle_staff_pin)):
    if runtime.system_health is None:
        raise HTTPException(status_code=503, detail='System inspection is not running')
    if req.enabled and not runtime.stt_service.preprocessing_status()['ffmpeg_available']:
        raise HTTPException(status_code=409, detail='ไม่พบ ffmpeg ในเครื่อง Backend ให้ติดตั้งก่อนเปิดตัวกรองเสียง')
    settings.STT_PREPROCESS_AUDIO = req.enabled
    return JSONResponse(runtime.system_health.snapshot(), headers={'Cache-Control': 'no-store'})


@router.post('/api/v1/staff/system/nodes/{node}/{action}')
async def staff_agent_control(
    node: Literal['intent', 'subtitle'], action: Literal['start', 'stop', 'restart', 'kill'],
    _: bool = Depends(verify_subtitle_staff_pin),
):
    if runtime.agent_processes is None:
        raise HTTPException(status_code=503, detail='Process manager is not running')
    try:
        await runtime.agent_processes.control(node, action)
    except ProcessControlError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    return JSONResponse(runtime.system_health.snapshot(), headers={'Cache-Control': 'no-store'})


@router.post("/api/v1/staff/mock-event", summary="Simulate ROS 2 perception and robot navigation state")
async def staff_mock_event(req: StaffMockEvent, _: bool = Depends(verify_staff_pin)):
    if runtime.ros_bridge_instance:
        runtime.ros_bridge_instance.inject_system_state(
            state=req.state,
            goal=req.goal,
            obstacle_detected=req.obstacle_detected,
            pose=req.pose
        )
    else:
        runtime.session_manager.update_from_ros_state(
            state=req.state,
            goal=req.goal,
            obstacle_detected=req.obstacle_detected,
            pose=req.pose
        )
    await runtime.ws_manager.broadcast_state()
    return {"status": "simulated"}
