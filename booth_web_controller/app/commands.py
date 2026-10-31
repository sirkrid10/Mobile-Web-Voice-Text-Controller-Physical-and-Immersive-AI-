"""Register, record and dispatch text requests from every input mode."""

from fastapi import HTTPException


async def submit_command(*, session_manager, bridge, broadcast, record_request,
                         session_id, token, text, input_mode):
    request_id, registered_session_id = await session_manager.begin_user_request(session_id, token)
    record_request(request_id, registered_session_id, text, input_mode)

    # Publish to ROS 2
    if bridge:
        try:
            bridge.publish_user_transcript(
                request_id=request_id,
                session_id=registered_session_id,
                input_mode=input_mode,
                text=text
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Unable to publish command: {exc}") from exc

    await broadcast()
    return {
        "status": "sent",
        "transcript": text,
        "inactivity_remaining_sec": session_manager.get_remaining_sec(),
        "request_id": request_id,
        "session_id": registered_session_id,
        "session_token": token
    }
