"""Connect the web application to real ROS transport and select its implementation."""

import os, asyncio, threading
from typing import Optional, Dict, Any

from app.bridge_base import BaseROS2Bridge
from app.config import settings
from app.direct_navigation import DirectNavigation
from app.mock_ros2_bridge import MockROS2Bridge
from app.ros_node import create_bridge_node
from app.subtitle_mode import SubtitleModeControl


class RealROS2Bridge(DirectNavigation, BaseROS2Bridge):
    def __init__(self, session_manager: Any, loop: asyncio.AbstractEventLoop):
        try:
            import rclpy
            from rclpy.executors import SingleThreadedExecutor
            from ai_interfaces.msg import UserRequest, IntentResult
            from ai_interfaces.action import GuideToDestination
            from action_msgs.msg import GoalStatus
            from rclpy.duration import Duration
        except ImportError as e:
            raise ImportError(
                f"[ROS2Bridge] Cannot start RealROS2Bridge: Required ROS 2 Jazzy or ai_interfaces packages missing: {e}. "
                "Ensure ROS 2 Jazzy and ai_interfaces workspace are sourced:\n"
                "  source /opt/ros/jazzy/setup.bash\n"
                "  source /home/windows_11/turtlebot_ws/install/setup.bash\n"
                "Silent fallback to JSON String is strictly prohibited."
            ) from e

        super().__init__(session_manager, loop)
        self.rclpy = rclpy
        self.UserRequest = UserRequest
        self.IntentResult = IntentResult
        self.GuideToDestination = GuideToDestination
        self.GoalStatus = GoalStatus
        self.Duration = Duration
        self.active_goal_handle = None
        self._active_goal_request_id: Optional[str] = None
        self._latest_action_request_id: Optional[str] = None

        if not rclpy.ok():
            rclpy.init()

        self.node = create_bridge_node(self)
        from rclpy.parameter import Parameter
        from rclpy.parameter_client import AsyncParameterClient
        self._intent_health_client = AsyncParameterClient(self.node, '/intent_node')
        self._subtitle_health_client = AsyncParameterClient(self.node, '/subtitle_node')
        self._subtitle_mode_control = SubtitleModeControl(
            AsyncParameterClient(self.node, '/subtitle_node'),
            lambda mode: Parameter('subtitle_mode', value=mode),
        )
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.thread.start()
        print("[ROS2Bridge] Real ROS 2 Jazzy Node running in daemon background thread.")

    async def inspect_connections(self):
        from app.ros_health import probe_parameters
        intent, subtitle = await asyncio.gather(
            probe_parameters(self._intent_health_client, ['clock_skew_sec']),
            probe_parameters(self._subtitle_health_client, ['subtitle_mode']),
        )
        return {
            'mode': 'real', 'intent': intent, 'subtitle': subtitle,
            'domain_id': os.environ.get('ROS_DOMAIN_ID', '0'),
            'discovery_server': os.environ.get('ROS_DISCOVERY_SERVER', ''),
            'graph_nodes': sorted(self.node.get_node_names()),
            'action_server_observed': self.node.action_client_navigate.server_is_ready(),
        }

    async def existing_agent_responds(self, name):
        from app.ros_health import probe_parameters
        client, parameter = (self._intent_health_client, 'clock_skew_sec') if name == 'intent' else (self._subtitle_health_client, 'subtitle_mode')
        return await probe_parameters(client, [parameter]) == 'responding'

    async def read_subtitle_mode(self):
        return await self._subtitle_mode_control.read()

    async def set_subtitle_mode(self, mode):
        return await self._subtitle_mode_control.write(mode)

    def _subtitle_now(self) -> float:
        return self.node.get_clock().now().nanoseconds / 1_000_000_000

    def publish_user_transcript(self, request_id: str, session_id: str, input_mode: str, text: str):
        """Publish native UserRequest to /guide/user_request for LLM intent parsing."""
        req_id = request_id

        msg_req = self.UserRequest()
        msg_req.request_id = req_id
        msg_req.session_id = session_id
        msg_req.text = text
        self.node.pub_user_request.publish(msg_req)
        self.session_manager.update_from_llm_mind(heard_text=text)
        print(f"[ROS2Bridge] Published native UserRequest to /guide/user_request: req_id={req_id}, session_id={session_id}, text='{text}'")

    def publish_high_level_action(self, action: str, target: str, explanation: str, source: str = "web_controller"):
        """System / Staff navigation command -> triggers /guide/navigate Action client."""
        print(f"[ROS2Bridge] Triggering Action /guide/navigate for destination '{target}' (source={source})")
        self.send_navigation_goal(destination_id=target, source=source)

    def publish_emergency_stop(self):
        """Cancel active action goal and send emergency stop signals."""
        self.cancel_navigation_goal()

        from std_msgs.msg import Bool
        from geometry_msgs.msg import Twist

        msg_bool = Bool()
        msg_bool.data = True
        self.node.pub_estop.publish(msg_bool)

        msg_twist = Twist()
        msg_twist.linear.x = 0.0
        msg_twist.angular.z = 0.0
        self.node.pub_cmd_vel.publish(msg_twist)
        print("[ROS2Bridge] Cancelled Action goal, published /robot/emergency_stop (True) and /cmd_vel (0.0)")

    def inject_system_state(self, state: str, goal: Optional[str] = None,
                            obstacle_detected: bool = False, pose: Optional[Dict[str, float]] = None):
        self.session_manager.update_from_ros_state(
            state=state, goal=goal, obstacle_detected=obstacle_detected, pose=pose
        )

    def shutdown(self):
        self._cancel_subtitle_timer()
        self.cancel_navigation_goal()
        try:
            if hasattr(self, "executor"):
                self.executor.shutdown()
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
        print("[ROS2Bridge] ROS 2 Jazzy and ai_interfaces detected! Initializing RealROS2Bridge...")
        return RealROS2Bridge(session_manager, loop)
    except ImportError as e:
        err_msg = (
            f"[ROS2Bridge] Cannot start RealROS2Bridge: Required ROS 2 Jazzy or ai_interfaces packages missing: {e}. "
            "Ensure you have sourced ROS 2 Jazzy and ai_interfaces workspace:\n"
            "  source /opt/ros/jazzy/setup.bash\n"
            "  source /home/windows_11/turtlebot_ws/install/setup.bash\n"
            "If running without ROS 2, set USE_MOCK_ROS2=true in .env."
        )
        print(err_msg)
        raise RuntimeError(err_msg) from e
