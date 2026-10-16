"""ROS 2 Jazzy Bridge & Mock Fallback.
Provides in-process ROS 2 rclpy Node in a background daemon thread,
publishing to /visitor/user_transcript, /llm/high_level_action, /robot/emergency_stop,
and subscribing to /robot/system_state, /llm/mind_status.
Falls back seamlessly to MockROS2Bridge if ROS 2 is not sourced or USE_MOCK_ROS2 is enabled.
"""

import json
import time
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
    """Simulates ROS 2 Nav2 and LLM Node behavior in standalone environment."""
    def __init__(self, session_manager: Any, loop: asyncio.AbstractEventLoop):
        self.session_manager = session_manager
        self.loop = loop
        self._sim_task: Optional[asyncio.Task] = None
        print("[ROS2Bridge] Mock ROS 2 Bridge initialized.")

    def publish_user_transcript(self, session_id: str, input_mode: str, text: str):
        payload = {
            "timestamp": time.time(),
            "session_id": session_id,
            "input_mode": input_mode,
            "text": text
        }
        print(f"[ROS2Bridge Mock] Published to /visitor/user_transcript: {json.dumps(payload, ensure_ascii=False)}")

        # Infer target location from text or default
        target = "AI_EXHIBITION"
        text_lower = text.lower()
        if "presentation" in text_lower or "????" in text_lower:
            target = "PRESENTATION_AREA"
        elif "robotics" in text_lower or "lab" in text_lower:
            target = "ROBOTICS_LAB"
        elif "start" in text_lower or "????????" in text_lower:
            target = "START_BOOTH"
        elif "stop" in text_lower or "????" in text_lower or "wait" in text_lower:
            target = None

        if target:
            self.session_manager.update_from_llm_mind(
                heard_text=text,
                target=target,
                explanation=f"????????????????????????????????????????? {target}"
            )
            self._start_navigation_simulation(target)
        else:
            self.session_manager.update_from_llm_mind(
                heard_text=text,
                target=self.session_manager.current_goal,
                explanation="?????????????/?? ???????????????????????????????"
            )
            self.session_manager.update_from_ros_state(state="IDLE")

    def publish_high_level_action(self, action: str, target: str, explanation: str, source: str = "web_controller"):
        payload = {
            "action": action,
            "target": target,
            "explanation": explanation,
            "source": source
        }
        print(f"[ROS2Bridge Mock] Published to /llm/high_level_action: {json.dumps(payload, ensure_ascii=False)}")

        if action == "GO_TO":
            self.session_manager.update_from_llm_mind(
                heard_text=f"?????? {source}: ?? {target}",
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
                # 1. Start navigating
                self.session_manager.update_from_ros_state(state="NAVIGATING", goal=target)
                print(f"[ROS2Bridge Mock] Navigating towards {target}...")
                await asyncio.sleep(4.0)

                # 2. Reached destination
                print(f"[ROS2Bridge Mock] Reached destination {target}!")
                self.session_manager.update_from_ros_state(state="REACHED", goal=target)
                self.session_manager.update_from_llm_mind(
                    heard_text=self.session_manager.heard_text,
                    target=target,
                    explanation=f"?????????????????? {target} ????????????? ???????????????????"
                )
            except asyncio.CancelledError:
                print("[ROS2Bridge Mock] Navigation simulation cancelled.")

        self._sim_task = asyncio.run_coroutine_threadsafe(_run_sim(), self.loop)


# ---------------------------------------------------------------------------
# Real ROS 2 Jazzy Bridge Implementation (rclpy In-Process Node)
# ---------------------------------------------------------------------------

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

                # Publishers
                self.pub_transcript = self.create_publisher(String, '/visitor/user_transcript', 10)
                self.pub_action = self.create_publisher(String, '/llm/high_level_action', 10)
                self.pub_estop = self.create_publisher(Bool, '/robot/emergency_stop', 10)
                self.pub_cmd_vel = self.create_publisher(Twist, '/cmd_vel', 10)

                # Subscribers
                self.sub_state = self.create_subscription(
                    String,
                    '/robot/system_state',
                    self._on_system_state,
                    10
                )
                self.sub_mind = self.create_subscription(
                    String,
                    '/llm/mind_status',
                    self._on_mind_status,
                    10
                )
                self.get_logger().info("BoothWebBridgeNode ROS 2 Jazzy node created.")

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
        payload = {
            "timestamp": time.time(),
            "session_id": session_id,
            "input_mode": input_mode,
            "text": text
        }
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.node.pub_transcript.publish(msg)
        print(f"[ROS2Bridge] Published /visitor/user_transcript: {msg.data}")

    def publish_high_level_action(self, action: str, target: str, explanation: str, source: str = "web_controller"):
        from std_msgs.msg import String
        payload = {
            "action": action,
            "target": target,
            "explanation": explanation,
            "source": source
        }
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.node.pub_action.publish(msg)
        print(f"[ROS2Bridge] Published /llm/high_level_action: {msg.data}")

    def publish_emergency_stop(self):
        from std_msgs.msg import Bool
        from geometry_msgs.msg import Twist
        msg_bool = Bool()
        msg_bool.data = True
        self.node.pub_estop.publish(msg_bool)

        # Zero velocity to halt TurtleBot3 instantly
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
