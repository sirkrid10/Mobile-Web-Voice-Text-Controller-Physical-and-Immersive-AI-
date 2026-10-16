"""ROS 2 Jazzy Bridge & Mock Fallback.
Aligned with TurtleBot3 LLM Subtitle Architecture (intent_node & subtitle_node).

Publishes to:
- /guide/user_request (UserRequest: request_id, session_id, text, valid_until)
- /guide/navigate (GuideToDestination: request_id, destination_id, valid_until)
- /visitor/user_transcript (std_msgs/String - fallback alias)
- /robot/emergency_stop & /cmd_vel

Subscribes to:
- /robot/navigation_state (NavigationState: stamp, request_id, destination_id, phase, ready_for_goal, distance_remaining_m, error_code, error_msg)
- /vr/subtitle (Subtitle: stamp, request_id, observation_id, text, ttl)
- /robot/system_state (fallback alias)
- /llm/mind_status (fallback alias)
"""

import json
import time
import secrets
import asyncio
import threading
from typing import Optional, Dict, Any, Callable

from app.config import settings


# ---------------------------------------------------------------------------
# Base Interface
# ---------------------------------------------------------------------------

class BaseROS2Bridge:
    def publish_user_transcript(self, session_id: str, input_mode: str, text: str):
        raise NotImplementedError

    def publish_high_level_action(self, action: str, target: str, explanation: str, source: str = "web_controller"):
        raise NotImplementedError

    def publish_emergency_stop(self):
        raise NotImplementedError

    def inject_system_state(self, state: str, goal: Optional[str] = None,
                            obstacle_detected: bool = False, pose: Optional[Dict[str, float]] = None):
        raise NotImplementedError

    def shutdown(self):
        pass


# ---------------------------------------------------------------------------
# Standalone Mock ROS 2 Bridge (For development, web testing & CI)
# ---------------------------------------------------------------------------

class MockROS2Bridge(BaseROS2Bridge):
    """Simulates ROS 2 Nav2, LLM intent_node, and subtitle_node in standalone environment."""
    def __init__(self, session_manager: Any, loop: asyncio.AbstractEventLoop):
        self.session_manager = session_manager
        self.loop = loop
        self._sim_task: Optional[asyncio.Task] = None
        print("[ROS2Bridge] Mock ROS 2 Bridge initialized (Aligned with /guide/user_request & /vr/subtitle).")

    def publish_user_transcript(self, session_id: str, input_mode: str, text: str):
        req_id = f"req-{secrets.token_hex(3)}"
        now_sec = int(time.time())

        # Exact UserRequest payload requested by LLM intent_node
        user_request_payload = {
            "request_id": req_id,
            "session_id": session_id,
            "text": text,
            "valid_until": {"sec": now_sec + 60, "nanosec": 0}
        }
        print(f"[ROS2Bridge Mock] Published to /guide/user_request: {json.dumps(user_request_payload, ensure_ascii=False)}")

        # Infer target destination_id: booth_09, booth_10, start
        target = "booth_09"
        text_lower = text.lower()
        if "คณิต" in text_lower or "10" in text_lower or "math" in text_lower or "stat" in text_lower:
            target = "booth_10"
        elif "คอม" in text_lower or "09" in text_lower or "computer" in text_lower or "วิทคอม" in text_lower:
            target = "booth_09"
        elif "start" in text_lower or "เริ่มต้น" in text_lower or "กลับ" in text_lower or "จุดรอ" in text_lower:
            target = "start"
        elif "stop" in text_lower or "หยุด" in text_lower or "wait" in text_lower:
            target = None

        if target:
            target_name = "บูธ 09 วิทยาการคอมพิวเตอร์" if target == "booth_09" else ("บูธ 10 คณิตศาสตร์และสถิติ" if target == "booth_10" else "จุดรอเริ่มต้น (Start)")
            self.session_manager.update_from_llm_mind(
                heard_text=text,
                target=target,
                explanation=f"intent_node เลือกปลายทาง: {target} ({target_name})"
            )
            self._start_navigation_simulation(target)
        else:
            self.session_manager.update_from_llm_mind(
                heard_text=text,
                target=self.session_manager.current_goal,
                explanation="รับคำสั่งหยุด/รอ หุ่นยนต์จอดประจำตำแหน่งชั่วคราว"
            )
            self.session_manager.update_from_ros_state(state="IDLE")

    def publish_high_level_action(self, action: str, target: str, explanation: str, source: str = "web_controller"):
        req_id = f"req-{secrets.token_hex(3)}"
        now_sec = int(time.time())
        guide_navigate_payload = {
            "request_id": req_id,
            "destination_id": target,
            "valid_until": {"sec": now_sec + 60, "nanosec": 0},
            "source": source,
            "explanation": explanation
        }
        print(f"[ROS2Bridge Mock] Published to /guide/navigate: {json.dumps(guide_navigate_payload, ensure_ascii=False)}")

        if action == "GO_TO":
            self.session_manager.update_from_llm_mind(
                heard_text=f"คำสั่ง {source}: ไป {target}",
                target=target,
                explanation=explanation
            )
            self._start_navigation_simulation(target)
        elif action in ("STOP", "WAIT"):
            self.publish_emergency_stop()

    def publish_emergency_stop(self):
        print("[ROS2Bridge Mock] Published to /robot/emergency_stop: True")
        if self._sim_task and not self._sim_task.done():
            self._sim_task.cancel()
        self.session_manager.update_from_ros_state(state="STOPPED")

    def inject_system_state(self, state: str, goal: Optional[str] = None,
                            obstacle_detected: bool = False, pose: Optional[Dict[str, float]] = None):
        print(f"[ROS2Bridge Mock] Injected system state: {state}, goal={goal}, obstacle={obstacle_detected}")
        self.session_manager.update_from_ros_state(
            state=state,
            goal=goal,
            obstacle_detected=obstacle_detected,
            pose=pose
        )

    def _start_navigation_simulation(self, target: str):
        if self._sim_task and not self._sim_task.done():
            self._sim_task.cancel()

        async def _run_sim():
            try:
                target_name = "บูธ 09 วิทยาการคอมพิวเตอร์" if target == "booth_09" else ("บูธ 10 คณิตศาสตร์และสถิติ" if target == "booth_10" else "จุดรอเริ่มต้น")
                # 1. Start navigating (phase: NAVIGATING)
                self.session_manager.update_from_ros_state(state="NAVIGATING", goal=target)
                self.session_manager.update_from_llm_mind(
                    heard_text=self.session_manager.heard_text,
                    target=target,
                    explanation=f"กำลังนำทางไป{target_name}"
                )
                print(f"[ROS2Bridge Mock] Navigating towards {target}...")
                await asyncio.sleep(4.0)

                # 2. Reached destination (phase: ARRIVED or HOME)
                final_state = "IDLE" if target == "start" else "REACHED"
                self.session_manager.update_from_ros_state(state=final_state, goal=target)
                self.session_manager.update_from_llm_mind(
                    heard_text=self.session_manager.heard_text,
                    target=target,
                    explanation=f"หุ่นยนต์เดินทางถึง {target_name} เรียบร้อยแล้ว พร้อมรับคำสั่งถัดไป"
                )
                print(f"[ROS2Bridge Mock] Reached destination {target} ({final_state})!")
            except asyncio.CancelledError:
                print("[ROS2Bridge Mock] Navigation simulation cancelled.")

        self._sim_task = asyncio.run_coroutine_threadsafe(_run_sim(), self.loop)


# ---------------------------------------------------------------------------
# Real ROS 2 Jazzy Bridge Implementation (rclpy In-Process Node)
# ---------------------------------------------------------------------------

try:
    from ai_interfaces.msg import UserRequest
    from builtin_interfaces.msg import Time as RosTime
    HAS_AI_INTERFACES = True
except ImportError:
    HAS_AI_INTERFACES = False


class RealROS2Bridge(BaseROS2Bridge):
    def __init__(self, session_manager: Any, loop: asyncio.AbstractEventLoop):
        import rclpy
        from rclpy.node import Node
        from std_msgs.msg import String, Bool
        from geometry_msgs.msg import Twist

        self.session_manager = session_manager
        self.loop = loop
        self.rclpy = rclpy

        if not rclpy.ok():
            rclpy.init()

        class BoothWebBridgeNode(Node):
            def __init__(self, outer: 'RealROS2Bridge'):
                super().__init__('booth_web_bridge_node')
                self.outer = outer

                # Publishers to LLM & Robot
                # Primary: /guide/user_request (UserRequest)
                if HAS_AI_INTERFACES:
                    self.pub_user_request = self.create_publisher(UserRequest, '/guide/user_request', 10)
                else:
                    self.pub_user_request = self.create_publisher(String, '/guide/user_request', 10)
                # Fallback alias: /visitor/user_transcript
                self.pub_transcript = self.create_publisher(String, '/visitor/user_transcript', 10)
                # Primary Action/Topic: /guide/navigate
                self.pub_guide_nav = self.create_publisher(String, '/guide/navigate', 10)
                self.pub_action = self.create_publisher(String, '/llm/high_level_action', 10)
                self.pub_estop = self.create_publisher(Bool, '/robot/emergency_stop', 10)
                self.pub_cmd_vel = self.create_publisher(Twist, '/cmd_vel', 10)

                # Subscribers from Robot bridge & subtitle_node
                # Primary: /robot/navigation_state (NavigationState)
                self.sub_nav_state = self.create_subscription(
                    String,
                    '/robot/navigation_state',
                    self._on_navigation_state,
                    10
                )
                # Fallback: /robot/system_state
                self.sub_state = self.create_subscription(
                    String,
                    '/robot/system_state',
                    self._on_system_state,
                    10
                )
                # Primary: /vr/subtitle (Subtitle from subtitle_node)
                self.sub_vr_subtitle = self.create_subscription(
                    String,
                    '/vr/subtitle',
                    self._on_vr_subtitle,
                    10
                )
                # Fallback: /llm/mind_status
                self.sub_mind = self.create_subscription(
                    String,
                    '/llm/mind_status',
                    self._on_mind_status,
                    10
                )
                self.get_logger().info("BoothWebBridgeNode ROS 2 Jazzy node created (Subscribed: /robot/navigation_state, /vr/subtitle; Publishing: /guide/user_request).")

            def _on_navigation_state(self, msg: String):
                """Parse /robot/navigation_state from Robot bridge."""
                try:
                    data = json.loads(msg.data)
                    phase = data.get("phase", "UNKNOWN").upper()
                    dest_id = data.get("destination_id")
                    ready_for_goal = data.get("ready_for_goal", False)
                    dist = data.get("distance_remaining_m", -1.0)
                    error_code = data.get("error_code", 0)
                    error_msg = data.get("error_msg", "")

                    # Map phase to internal robot_state
                    if phase in ("NAVIGATING", "RETURNING_HOME"):
                        mapped_state = "NAVIGATING"
                    elif phase == "ARRIVED":
                        mapped_state = "REACHED"
                    elif phase in ("HOME", "READY"):
                        mapped_state = "IDLE"
                    elif phase in ("CANCELED", "NOT_READY"):
                        mapped_state = "STOPPED"
                    elif phase == "FAILED":
                        mapped_state = "FAILED"
                    else:
                        mapped_state = "IDLE"

                    def _sync():
                        self.outer.session_manager.update_from_ros_state(
                            state=mapped_state,
                            goal=dest_id,
                            obstacle_detected=False
                        )
                    self.outer.loop.call_soon_threadsafe(_sync)
                except Exception as e:
                    self.get_logger().error(f"Error parsing /robot/navigation_state: {e}")

            def _on_vr_subtitle(self, msg: String):
                """Parse /vr/subtitle from subtitle_node to display synchronized subtitle on mobile screen."""
                try:
                    data = json.loads(msg.data)
                    text = data.get("text", "")
                    def _sync():
                        if text:
                            self.outer.session_manager.update_from_llm_mind(
                                heard_text=self.outer.session_manager.heard_text,
                                explanation=text
                            )
                    self.outer.loop.call_soon_threadsafe(_sync)
                except Exception as e:
                    self.get_logger().error(f"Error parsing /vr/subtitle: {e}")

            def _on_system_state(self, msg: String):
                try:
                    data = json.loads(msg.data)
                    state = data.get("state", "IDLE")
                    goal = data.get("goal")
                    obstacle = data.get("obstacle_detected", False)
                    pose = data.get("pose")

                    def _sync():
                        self.outer.session_manager.update_from_ros_state(
                            state=state, goal=goal, obstacle_detected=obstacle, pose=pose
                        )
                    self.outer.loop.call_soon_threadsafe(_sync)
                except Exception as e:
                    self.get_logger().error(f"Error parsing /robot/system_state: {e}")

            def _on_mind_status(self, msg: String):
                try:
                    data = json.loads(msg.data)
                    heard = data.get("heard_text", "")
                    target = data.get("target")
                    explanation = data.get("explanation")

                    def _sync():
                        self.outer.session_manager.update_from_llm_mind(
                            heard_text=heard, target=target, explanation=explanation
                        )
                    self.outer.loop.call_soon_threadsafe(_sync)
                except Exception as e:
                    self.get_logger().error(f"Error parsing /llm/mind_status: {e}")

        self.node = BoothWebBridgeNode(self)
        self.thread = threading.Thread(target=self.rclpy.spin, args=(self.node,), daemon=True)
        self.thread.start()
        print("[ROS2Bridge] In-process rclpy Node running in background daemon thread.")

    def publish_user_transcript(self, session_id: str, input_mode: str, text: str):
        from std_msgs.msg import String

        req_id = f"req-{secrets.token_hex(4)}"
        now_sec = int(time.time())

        # Exact schema required by LLM intent_node (/guide/user_request)
        if HAS_AI_INTERFACES:
            msg_req = UserRequest()
            msg_req.request_id = req_id
            msg_req.session_id = session_id
            msg_req.text = text
            msg_req.valid_until = RosTime(sec=now_sec + 60, nanosec=0)
            self.node.pub_user_request.publish(msg_req)
            print(f"[ROS2Bridge] Published native UserRequest to /guide/user_request: req_id={req_id}, text={text}")
        else:
            user_request_data = {
                "request_id": req_id,
                "session_id": session_id,
                "text": text,
                "valid_until": {"sec": now_sec + 60, "nanosec": 0}
            }
            msg_req = String()
            msg_req.data = json.dumps(user_request_data, ensure_ascii=False)
            self.node.pub_user_request.publish(msg_req)
            print(f"[ROS2Bridge] Published JSON String to /guide/user_request: {msg_req.data}")

        # Fallback alias /visitor/user_transcript
        msg_trans = String()
        msg_trans.data = json.dumps({
            "timestamp": time.time(),
            "session_id": session_id,
            "input_mode": input_mode,
            "text": text
        }, ensure_ascii=False)
        self.node.pub_transcript.publish(msg_trans)

    def publish_high_level_action(self, action: str, target: str, explanation: str, source: str = "web_controller"):
        from std_msgs.msg import String

        req_id = f"req-{secrets.token_hex(4)}"
        now_sec = int(time.time())

        # Primary: /guide/navigate
        guide_data = {
            "request_id": req_id,
            "destination_id": target,
            "valid_until": {"sec": now_sec + 60, "nanosec": 0},
            "source": source
        }
        msg_guide = String()
        msg_guide.data = json.dumps(guide_data, ensure_ascii=False)
        self.node.pub_guide_nav.publish(msg_guide)
        print(f"[ROS2Bridge] Published /guide/navigate: {msg_guide.data}")

        # Fallback alias: /llm/high_level_action
        msg_act = String()
        msg_act.data = json.dumps({
            "action": action,
            "target": target,
            "explanation": explanation,
            "source": source
        }, ensure_ascii=False)
        self.node.pub_action.publish(msg_act)

    def publish_emergency_stop(self):
        from std_msgs.msg import Bool
        from geometry_msgs.msg import Twist
        msg_bool = Bool()
        msg_bool.data = True
        self.node.pub_estop.publish(msg_bool)

        msg_twist = Twist()
        msg_twist.linear.x = 0.0
        msg_twist.angular.z = 0.0
        self.node.pub_cmd_vel.publish(msg_twist)
        print("[ROS2Bridge] Published /robot/emergency_stop (True) and /cmd_vel (0.0)")

    def inject_system_state(self, state: str, goal: Optional[str] = None,
                            obstacle_detected: bool = False, pose: Optional[Dict[str, float]] = None):
        self.session_manager.update_from_ros_state(
            state=state, goal=goal, obstacle_detected=obstacle_detected, pose=pose
        )

    def shutdown(self):
        try:
            self.node.destroy_node()
            if self.rclpy.ok():
                self.rclpy.shutdown()
        except Exception as e:
            print(f"[ROS2Bridge] Error during shutdown: {e}")


# ---------------------------------------------------------------------------
# Factory Function
# ---------------------------------------------------------------------------

def create_ros2_bridge(session_manager: Any, loop: asyncio.AbstractEventLoop) -> BaseROS2Bridge:
    if settings.USE_MOCK_ROS2:
        print("[ROS2Bridge] USE_MOCK_ROS2 is enabled in config. Using MockROS2Bridge.")
        return MockROS2Bridge(session_manager, loop)

    try:
        import rclpy
        print("[ROS2Bridge] rclpy detected! Initializing RealROS2Bridge...")
        return RealROS2Bridge(session_manager, loop)
    except (ImportError, Exception) as e:
        print(f"[ROS2Bridge] rclpy not available ({e}). Falling back to MockROS2Bridge.")
        return MockROS2Bridge(session_manager, loop)
