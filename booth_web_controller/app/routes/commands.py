"""HTTP adapters for commands operations."""

from typing import Optional

from fastapi import Header, HTTPException, UploadFile, File, APIRouter

from app import runtime
from app.commands import submit_command
from app.models import TextCommandRequest, CommandResponse
from app.stt_service import STTUnavailableError


router = APIRouter()


@router.post("/api/v1/command/voice", response_model=CommandResponse, summary="Submit voice recording (WebM/MP4)")
async def command_voice(
    audio: UploadFile = File(...),
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id")
):
    if not x_session_id:
        raise HTTPException(status_code=400, detail="Missing X-Session-Id header")

    # Validate claim or auto-claim
    validated_token = await runtime.session_manager.validate_or_auto_claim(x_session_id, x_session_token)

    # Transcribe speech
    try:
        transcript = await runtime.stt_service.transcribe_audio(audio)
    except STTUnavailableError as exc:
        raise HTTPException(status_code=503, detail="ระบบแปลงเสียงไม่พร้อมใช้งาน กรุณาลองใหม่ภายหลัง") from exc
    if not transcript or not transcript.strip():
        raise HTTPException(status_code=422, detail="ไม่พบข้อความจากเสียง")
    transcript = transcript.strip()

    return await submit_command(
        session_manager=runtime.session_manager, bridge=runtime.ros_bridge_instance,
        broadcast=runtime.ws_manager.broadcast_state, record_request=runtime.record_web_request,
        session_id=x_session_id, token=validated_token, text=transcript, input_mode='voice',
    )


@router.post("/api/v1/command/text", response_model=CommandResponse, summary="Submit text or quick chip command")
async def command_text(
    req: TextCommandRequest,
    x_session_token: Optional[str] = Header(None, alias="X-Session-Token"),
    x_session_id: Optional[str] = Header(None, alias="X-Session-Id")
):
    if not x_session_id:
        raise HTTPException(status_code=400, detail="Missing X-Session-Id header")

    # Validate claim or auto-claim
    validated_token = await runtime.session_manager.validate_or_auto_claim(x_session_id, x_session_token)
    return await submit_command(
        session_manager=runtime.session_manager, bridge=runtime.ros_bridge_instance,
        broadcast=runtime.ws_manager.broadcast_state, record_request=runtime.record_web_request,
        session_id=x_session_id, token=validated_token, text=req.text, input_mode=req.input_mode,
    )
