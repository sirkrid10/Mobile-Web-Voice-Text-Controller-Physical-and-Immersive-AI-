"""HTTP adapters for sockets operations."""

from fastapi import WebSocket, WebSocketDisconnect, APIRouter

from app import runtime


router = APIRouter()


@router.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    await runtime.ws_manager.connect(websocket)
    try:
        while True:
            # Keep receiving pings / client messages
            data = await websocket.receive_text()
    except WebSocketDisconnect:
        await runtime.ws_manager.disconnect(websocket)
    except Exception:
        await runtime.ws_manager.disconnect(websocket)


@router.websocket("/ws/vr/subtitle")
async def websocket_vr_subtitle(websocket: WebSocket):
    await runtime.vr_subtitles.serve(websocket)
