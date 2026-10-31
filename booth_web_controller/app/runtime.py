"""Own application service instances, startup and shutdown."""

from contextlib import asynccontextmanager
import os, asyncio, uuid
from typing import Optional

from fastapi import FastAPI

from app import stt_service as speech
from app.agent_processes import AgentProcesses
from app.bridge_base import BaseROS2Bridge
from app.config import settings
from app.connections import ConnectionManager
from app.dialogue_history import DialogueHistory
from app.ros2_bridge import create_ros2_bridge
from app.session_manager import session_manager
from app.system_health import SystemHealth
from app.tunnel_manager import TunnelManager
from app.vr_subtitle import VRSubtitleHub


stt_service = speech.stt_service
ws_manager = ConnectionManager(lambda: session_manager.get_state_broadcast())
vr_subtitles = VRSubtitleHub()
ros_bridge_instance: Optional[BaseROS2Bridge] = None
watchdog_task: Optional[asyncio.Task] = None
agent_processes: Optional[AgentProcesses] = None
system_health: Optional[SystemHealth] = None
tunnel_manager: Optional[TunnelManager] = None
dialogue_history: Optional[DialogueHistory] = None
INSTANCE_ID = str(uuid.uuid4())


def receive_subtitle(text, stamp, request_id='', observation_id=''):
    vr_subtitles.publish(text, stamp, request_id, observation_id)
    if text.strip():
        record_dialogue('subtitle', text=text, request_id=request_id, observation_id=observation_id)


def record_dialogue(kind, **values):
    if dialogue_history is not None:
        try:
            dialogue_history.record(kind, **values)
        except Exception:
            dialogue_history.error = 'history_write_failed'


def record_web_request(request_id, session_id, text, input_mode):
    record_dialogue('request', request_id=request_id, session_id=session_id, text=text, input_mode=input_mode)


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
    global ros_bridge_instance, watchdog_task, agent_processes, system_health, tunnel_manager, dialogue_history
    loop = asyncio.get_running_loop()

    # 1. Initialize ROS 2 Bridge (Real or Mock)
    ros_bridge_instance = create_ros2_bridge(session_manager, loop)
    vr_subtitles.reset()
    ros_bridge_instance.set_subtitle_callback(receive_subtitle)
    session_manager.set_ros_bridge(ros_bridge_instance)
    session_manager.set_broadcast_callback(ws_manager.broadcast_state)

    agent_processes = AgentProcesses(
        settings.AGENT_WORKSPACE,
        enabled=settings.MANAGE_AGENT_NODES and not settings.USE_MOCK_ROS2,
        clock_skew=settings.AGENT_CLOCK_SKEW_SEC,
        probe_external=ros_bridge_instance.existing_agent_responds,
    )
    try:
        await agent_processes.open()
        dialogue_history = DialogueHistory(settings.DIALOGUE_HISTORY_PATH or None,
            scope=os.path.dirname(os.path.dirname(__file__)),
            secrets=(settings.STAFF_PIN, settings.GROQ_API_KEY, settings.OPENAI_API_KEY, settings.CLOUDFLARE_API_TOKEN))
        session_manager.set_history_callback(record_dialogue)
        tunnel_manager = TunnelManager(
            enabled=settings.ENABLE_TUNNEL, port=settings.PORT, instance_id=INSTANCE_ID,
            worker_static_url=settings.WORKER_STATIC_URL, cf_api_token=settings.CLOUDFLARE_API_TOKEN,
            cf_account_id=settings.CLOUDFLARE_ACCOUNT_ID,
            cf_namespace_id=settings.CLOUDFLARE_KV_NAMESPACE_ID, cf_key=settings.CLOUDFLARE_KV_KEY,
        )
        try:
            await tunnel_manager.start()
        except Exception as exc:
            tunnel_manager.last_error = f"Tunnel manager failed to start ({type(exc).__name__})"
        system_health = SystemHealth(ros_bridge_instance, agent_processes, vr_subtitles,
                                    mock=settings.USE_MOCK_ROS2, tunnel_manager=tunnel_manager)
        system_health.start()
        watchdog_task = asyncio.create_task(session_watchdog_loop())
        yield
    finally:
        if tunnel_manager:
            await tunnel_manager.stop()
        if system_health:
            await system_health.close()
        try:
            if agent_processes:
                await agent_processes.close()
        finally:
            if watchdog_task and not watchdog_task.done():
                watchdog_task.cancel()
                await asyncio.gather(watchdog_task, return_exceptions=True)
            if ros_bridge_instance:
                ros_bridge_instance.shutdown()
            session_manager.set_history_callback(None)
            if dialogue_history:
                dialogue_history.close()
            dialogue_history = None
            system_health = None
            agent_processes = None
            tunnel_manager = None
            print("[Main] Shutdown complete.")
