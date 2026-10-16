"""ROS 2 Jazzy Bridge for TurtleBot3 Mobile Web Voice & Text Controller.
Fully aligned with TurtleBot3 LLM Subtitle Architecture (ai_interfaces).

Contract Topics & Actions:
- /guide/user_request       : ai_interfaces/msg/UserRequest        (Publish)
- /robot/navigation_state   : ai_interfaces/msg/NavigationState    (Subscribe)
- /vr/subtitle              : ai_interfaces/msg/Subtitle           (Subscribe)
- /guide/navigate           : ai_interfaces/action/GuideToDestination (Action Client)
- /robot/emergency_stop     : std_msgs/msg/Bool                    (Publish)
- /cmd_vel                  : geometry_msgs/msg/Twist              (Publish)
"""

import os
import time
import json
import secrets
import asyncio
import threading
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any

from app.config import settings


# ---------------------------------------------------------------------------
# Base Bridge Contract
# ---------------------------------------------------------------------------

class BaseROS2Bridge(ABC):
    @abstractmethod
    def publish_user_transcript(self, session_id: str, input_mode: str, text: str):
        """Publish visitor request to /guide/user_request for LLM intent parsing."""
        pass

    @abstractmethod
    def publish_high_level_action(self, action: str, target: str, explanation: str, source: str = "web_controller"):
        """Trigger direct navigation command (e.g. Return to Start, Staff override) via Action."""
        pass

    @abstractmethod
    def send_navigation_goal(self, destination_id: str, request_id: Optional[str] = None):
        """Send navigation Action goal to /guide/navigate."""
        pass

    @abstractmethod
    def cancel_navigation_goal(self):
        """Cancel active navigation Action goal."""
        pass

    @abstractmethod
    def publish_emergency_stop(self):
        """Trigger immediate emergency stop and cancel active goals."""
        pass

    @abstractmethod
    def inject_system_state(self, state: str, goal: Optional[str] = None,
                            obstacle_detected: bool = False, pose: Optional[Dict[str, float]] = None):
        """Manually inject robot state (used by staff test panel)."""
        pass

    @abstractmethod
    def shutdown(self):
        """Gracefully release bridge resources."""
        pass


# ---------------------------------------------------------------------------
# Mock Bridge Implementation (Simulation for development & offline tests)
# ---------------------------------------------------------------------------

class MockROS2Bridge(BaseROS2Bridge):
    def __init__(self, session_manager: Any, loop: asyncio.AbstractEventLoop):
        self.session_manager = session_manager
        self.loop = loop
        self._sim_task: Optional[asyncio.Task] = None
        self._subtitle_timer: Optional[asyncio.Task] = None
        self._latest_subtitle_stamp: float = 0.0
        print("[ROS2Bridge Mock] Running in standalone mock mode (USE_MOCK_ROS2=true).")

    def publish_user_transcript(self, session_id: str, input_mode: str, text: str):
        req_id = f"req-{secrets.token_hex(4)}"
        print(f"[ROS2Bridge Mock] Published to /guide/user_request: req_id={req_id}, session_id={session_id}, text='{text}'")

        # Mock LLM intent parsing for target destination
        target = "booth_09"
        text_lower = text.lower()
        if "คณิต" in text_lower or "10" in text_lower or "math" in text_lower or "stat" in text_lower:
            target = "booth_10"
        elif "คอม" in text_lower or "09" in text_lower or "computer" in text_lower or "วิทคอม" in text_lower or "cs" in text_lower:
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
                explanation="รับคำสั่งหยุดรอ หุ่นยนต์หยุดรอตรงนี้ชั่วคราว"
            )

    def publish_high_level_action(self, action: str, target: str, explanation: str, source: str = "web_controller"):
        print(f"[ROS2Bridge Mock] Direct navigation action requested: target={target}, source={source}")
        self.send_navigation_goal(destination_id=target)

    def send_navigation_goal(self, destination_id: str, request_id: Optional[str] = None):
        req_id = request_id or f"req-{secrets.token_hex(4)}"
        print(f"[ROS2Bridge Mock] Action /guide/navigate Goal sent: req_id={req_id}, dest={destination_id}")
        self._start_navigation_simulation(destination_id)

    def cancel_navigation_goal(self):
        if self._sim_task and not self._sim_task.done():
            self._sim_task.cancel()
            self._sim_task = None
            print("[ROS2Bridge Mock] Cancelled active navigation Action goal.")

    def publish_emergency_stop(self):
        self.cancel_navigation_goal()
        self.session_manager.update_from_ros_state(state="STOPPED")
        print("[ROS2Bridge Mock] Emergency stop executed.")

    def handle_mock_subtitle(self, text: str, ttl_sec: float = 5.0, stamp_sec: float = 0.0):
        """Simulate receiving Subtitle message."""
        now = time.time()
        stamp = stamp_sec or now

        if stamp < self._latest_subtitle_stamp:
            return
        self._latest_subtitle_stamp = stamp

        if not text or not text.strip() or ttl_sec <= 0:
            if self._subtitle_timer and not self._subtitle_timer.done():
                self._subtitle_timer.cancel()
            self.session_manager.llm_explanation = ""
            self.session_manager._trigger_broadcast()
            return

        self.session_manager.update_from_llm_mind(
            heard_text=self.session_manager.heard_text,
            explanation=text
        )

        if self._subtitle_timer and not self._subtitle_timer.done():
            self._subtitle_timer.cancel()

        async def _clear_sub():
            try:
                await asyncio.sleep(ttl_sec)
                if self._latest_subtitle_stamp <= stamp:
                    self.session_manager.llm_explanation = ""
                    self.session_manager._trigger_broadcast()
            except asyncio.CancelledError:
                pass

        self._subtitle_timer = asyncio.run_coroutine_threadsafe(_clear_sub(), self.loop)

    def inject_system_state(self, state: str, goal: Optional[str] = None,
                            obstacle_detected: bool = False, pose: Optional[Dict[str, float]] = None):
        self.session_manager.update_from_ros_state(
            state=state, goal=goal, obstacle_detected=obstacle_detected, pose=pose
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

    def shutdown(self):
        if self._sim_task and not self._sim_task.done():
            self._sim_task.cancel()
        if self._subtitle_timer and not self._subtitle_timer.done():
            self._subtitle_timer.cancel()


# ---------------------------------------------------------------------------
# Real ROS 2 Jazzy Bridge Implementation (In-Process rclpy Node)
# ---------------------------------------------------------------------------

class RealROS2Bridge(BaseROS2Bridge):
    def __init__(self, session_manager: Any, loop: asyncio.AbstractEventLoop):
        try:
            import rclpy
            from rclpy.node import Node
            from rclpy.action import ActionClient
            from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
            from action_msgs.msg import GoalStatus
            from ai_interfaces.msg import UserRequest, NavigationState, Subtitle
            from ai_interfaces.action import GuideToDestination
            from std_msgs.msg import Bool
            from geometry_msgs.msg import Twist
        except ImportError as e:
            raise ImportError(
                f"[ROS2Bridge] Cannot start RealROS2Bridge: Required ROS 2 Jazzy or ai_interfaces packages missing: {e}. "
                "Ensure ROS 2 Jazzy and ai_interfaces workspace are sourced:\n"
                "  source /opt/ros/jazzy/setup.bash\n"
                "  source /home/windows_11/turtlebot_ws/install/setup.bash\n"
                "Silent fallback to JSON String is strictly prohibited."
            ) from e

        self.session_manager = session_manager
        self.loop = loop
        self.rclpy = rclpy
        self.UserRequest = UserRequest
        self.GuideToDestination = GuideToDestination
        self.active_goal_handle = None
        self._subtitle_timer: Optional[asyncio.Task] = None
        self._latest_subtitle_stamp: float = 0.0

        if not rclpy.ok():
            rclpy.init()

        # Contract QoS: Reliable, Volatile, Depth 10
        qos_profile = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )

        outer = self

        class BoothWebBridgeNode(Node):
            def __init__(self):
                super().__init__('booth_web_bridge_node')

                # 1. Publisher: /guide/user_request (UserRequest)
                self.pub_user_request = self.create_publisher(
                    UserRequest,
                    '/guide/user_request',
                    qos_profile
                )

                # 2. Action Client: /guide/navigate (GuideToDestination)
                self.action_client_navigate = ActionClient(
                    self,
                    GuideToDestination,
                    '/guide/navigate'
                )

                # 3. Emergency Stop & Command Velocity
                self.pub_estop = self.create_publisher(Bool, '/robot/emergency_stop', 10)
                self.pub_cmd_vel = self.create_publisher(Twist, '/cmd_vel', 10)

                # 4. Subscriber: /robot/navigation_state (NavigationState)
                self.sub_nav_state = self.create_subscription(
                    NavigationState,
                    '/robot/navigation_state',
                    self._on_navigation_state,
                    qos_profile
                )

                # 5. Subscriber: /vr/subtitle (Subtitle)
                self.sub_subtitle = self.create_subscription(
                    Subtitle,
                    '/vr/subtitle',
                    self._on_vr_subtitle,
                    qos_profile
                )

            def _on_navigation_state(self, msg: NavigationState):
                """Handle /robot/navigation_state updates directly from NavigationState."""
                try:
                    phase = (msg.phase or "").upper()
                    dest_id = msg.destination_id
                    ready_for_goal = msg.ready_for_goal
                    dist = msg.distance_remaining_m
                    error_code = msg.error_code
                    error_msg = msg.error_msg

                    self.get_logger().info(
                        f"[/robot/navigation_state] phase={phase}, dest={dest_id}, ready={ready_for_goal}, dist={dist:.2f}m"
                    )

                    # State mapping aligned with contract:
                    # - NAVIGATING / RETURNING_HOME: In motion (watchdog timer paused)
                    # - ARRIVED: Arrived at booth (session remains active, countdown runs)
                    # - HOME + ready_for_goal: Back at start point and ready for new task -> IDLE
                    # - READY: Ready for goal -> IDLE
                    # - CANCELED / NOT_READY: Stopped
                    # - FAILED: Failed
                    if phase in ("NAVIGATING", "RETURNING_HOME"):
                        mapped_state = "NAVIGATING"
                    elif phase == "ARRIVED":
                        mapped_state = "REACHED"
                    elif phase == "HOME":
                        if ready_for_goal:
                            mapped_state = "IDLE"
                        else:
                            mapped_state = "NAVIGATING"
                    elif phase == "READY":
                        mapped_state = "IDLE"
                    elif phase in ("CANCELED", "NOT_READY"):
                        mapped_state = "STOPPED"
                    elif phase == "FAILED":
                        mapped_state = "FAILED"
                    else:
                        mapped_state = "IDLE"

                    def _sync():
                        outer.session_manager.update_from_ros_state(
                            state=mapped_state,
                            goal=dest_id,
                            obstacle_detected=False
                        )
                    outer.loop.call_soon_threadsafe(_sync)
                except Exception as e:
                    self.get_logger().error(f"Error handling /robot/navigation_state: {e}")

            def _on_vr_subtitle(self, msg: Subtitle):
                """Handle /vr/subtitle updates with strict TTL and auto-clearing rules."""
                try:
                    stamp_sec = msg.stamp.sec + msg.stamp.nanosec * 1e-9
                    ttl_sec = msg.ttl.sec + msg.ttl.nanosec * 1e-9
                    text = (msg.text or "").strip()

                    # Rule 3: Discard if stamp is older than latest seen message
                    if stamp_sec > 0 and stamp_sec < outer._latest_subtitle_stamp:
                        self.get_logger().debug(
                            f"Discarding outdated subtitle (stamp={stamp_sec} < latest={outer._latest_subtitle_stamp})"
                        )
                        return

                    if stamp_sec > outer._latest_subtitle_stamp:
                        outer._latest_subtitle_stamp = stamp_sec

                    # Rule 2: Empty text with TTL 0 -> clear immediately
                    if not text or ttl_sec <= 0:
                        self.get_logger().info("Received empty subtitle or TTL <= 0 -> Clearing subtitle immediately")
                        def _clear():
                            outer._cancel_subtitle_timer()
                            outer.session_manager.llm_explanation = ""
                            outer.session_manager._trigger_broadcast()
                        outer.loop.call_soon_threadsafe(_clear)
                        return

                    # Rule 1 & 4: Display text, and schedule auto-clear at stamp + ttl
                    now_sec = time.time()
                    if stamp_sec > 0 and (stamp_sec + ttl_sec) < now_sec:
                        self.get_logger().debug("Discarding expired subtitle message")
                        return

                    def _display():
                        outer._cancel_subtitle_timer()
                        outer.session_manager.update_from_llm_mind(
                            heard_text=outer.session_manager.heard_text,
                            explanation=msg.text
                        )
                        outer._schedule_subtitle_clear(ttl_sec, stamp_sec)

                    outer.loop.call_soon_threadsafe(_display)
                except Exception as e:
                    self.get_logger().error(f"Error handling /vr/subtitle: {e}")

        from rclpy.executors import SingleThreadedExecutor
        self.node = BoothWebBridgeNode()
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.thread.start()
        print("[ROS2Bridge] Real ROS 2 Jazzy Node running in daemon background thread.")

    def _schedule_subtitle_clear(self, delay: float, stamp: float):
        self._cancel_subtitle_timer()

        async def _clear_after_delay():
            try:
                await asyncio.sleep(max(0.1, delay))
                if self._latest_subtitle_stamp <= stamp:
                    self.session_manager.llm_explanation = ""
                    self.session_manager._trigger_broadcast()
                    print(f"[ROS2Bridge] Subtitle cleared automatically after TTL ({delay:.1f}s)")
            except asyncio.CancelledError:
                pass

        self._subtitle_timer = asyncio.create_task(_clear_after_delay())

    def _cancel_subtitle_timer(self):
        if self._subtitle_timer and not self._subtitle_timer.done():
            self._subtitle_timer.cancel()
            self._subtitle_timer = None

    def publish_user_transcript(self, session_id: str, input_mode: str, text: str):
        """Publish native UserRequest to /guide/user_request for LLM intent parsing."""
        req_id = f"req-{secrets.token_hex(4)}"

        msg_req = self.UserRequest()
        msg_req.request_id = req_id
        msg_req.session_id = session_id
        msg_req.text = text
        self.node.pub_user_request.publish(msg_req)
        print(f"[ROS2Bridge] Published native UserRequest to /guide/user_request: req_id={req_id}, session_id={session_id}, text='{text}'")

    def publish_high_level_action(self, action: str, target: str, explanation: str, source: str = "web_controller"):
        """System / Staff navigation command -> triggers /guide/navigate Action client."""
        print(f"[ROS2Bridge] Triggering Action /guide/navigate for destination '{target}' (source={source})")
        self.send_navigation_goal(destination_id=target)

    def send_navigation_goal(self, destination_id: str, request_id: Optional[str] = None):
        """Send ROS 2 Action Goal to /guide/navigate (GuideToDestination)."""
        req_id = request_id or f"req-{secrets.token_hex(4)}"

        if not self.node.action_client_navigate.wait_for_server(timeout_sec=2.0):
            self.node.get_logger().error("Action server /guide/navigate is not available!")
            return

        goal_msg = self.GuideToDestination.Goal()
        goal_msg.request_id = req_id
        goal_msg.destination_id = destination_id

        self.node.get_logger().info(f"Sending Action Goal to /guide/navigate: req_id={req_id}, dest={destination_id}")

        send_future = self.node.action_client_navigate.send_goal_async(
            goal_msg,
            feedback_callback=self._on_action_feedback
        )
        send_future.add_done_callback(self._on_goal_response)

    def _on_action_feedback(self, feedback_msg):
        dist = feedback_msg.feedback.distance_remaining_m
        self.node.get_logger().debug(f"Action /guide/navigate feedback: distance_remaining={dist:.2f}m")

    def _on_goal_response(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.node.get_logger().warn("Action Goal rejected by /guide/navigate server!")
            return

        self.node.get_logger().info("Action Goal accepted by /guide/navigate server.")
        self.active_goal_handle = goal_handle

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._on_goal_result)

    def _on_goal_result(self, future):
        result_wrapper = future.result()
        status = result_wrapper.status
        result = result_wrapper.result
        self.node.get_logger().info(
            f"Action /guide/navigate finished: status={status}, error_code={result.error_code}, msg='{result.error_msg}'"
        )
        self.active_goal_handle = None

    def cancel_navigation_goal(self):
        """Cancel active Action goal using ROS Action cancel mechanism."""
        if self.active_goal_handle is not None:
            self.node.get_logger().info("Cancelling active /guide/navigate Action goal...")
            self.active_goal_handle.cancel_goal_async()
            self.active_goal_handle = None

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
        import rclpy
        from ai_interfaces.msg import UserRequest, NavigationState, Subtitle
        from ai_interfaces.action import GuideToDestination
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
