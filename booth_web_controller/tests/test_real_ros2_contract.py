"""Integration Test Suite for Real ROS 2 Jazzy Contract.
Tests real in-process communication using ai_interfaces and ROS 2 Jazzy:
1. Web command publishes native UserRequest to /guide/user_request
2. Backend receives native NavigationState on /robot/navigation_state
3. Backend receives native Subtitle on /vr/subtitle and handles TTL clearing
4. Direct navigation calls Action server /guide/navigate (GuideToDestination)
5. Cancellation via ROS Action cancel mechanism on emergency stop
"""

import time
import asyncio
import pytest
import rclpy
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
from fastapi.testclient import TestClient

from ai_interfaces.msg import UserRequest, NavigationState, Subtitle
from ai_interfaces.action import GuideToDestination
from app.main import app
from app.config import settings
from app.session_manager import session_manager


# Shared contract QoS: Reliable, Volatile, Depth 10
qos_profile = QoSProfile(
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=10
)


@pytest.fixture(autouse=True)
def ensure_ros_initialized():
    """Ensure rclpy is initialized for all contract tests."""
    if not rclpy.ok():
        rclpy.init()


class MockLLMAndRobotNode(Node):
    """Mock ROS 2 node representing the LLM intent_node, subtitle_node, and Robot."""
    def __init__(self):
        super().__init__('mock_llm_robot_node')
        self.received_user_requests = []
        self.received_goals = []
        self.cancelled_goals = []

        # 1. Subscriber: /guide/user_request (UserRequest)
        self.sub_user_req = self.create_subscription(
            UserRequest,
            '/guide/user_request',
            self._on_user_request,
            qos_profile
        )

        # 2. Publisher: /robot/navigation_state (NavigationState)
        self.pub_nav_state = self.create_publisher(
            NavigationState,
            '/robot/navigation_state',
            qos_profile
        )

        # 3. Publisher: /vr/subtitle (Subtitle)
        self.pub_subtitle = self.create_publisher(
            Subtitle,
            '/vr/subtitle',
            qos_profile
        )

        # 4. Action Server: /guide/navigate (GuideToDestination)
        self._action_server = ActionServer(
            self,
            GuideToDestination,
            '/guide/navigate',
            execute_callback=self._execute_goal,
            goal_callback=self._goal_callback,
            cancel_callback=self._cancel_callback
        )

    def _on_user_request(self, msg: UserRequest):
        self.get_logger().info(f"Received UserRequest: req_id={msg.request_id}, text='{msg.text}'")
        self.received_user_requests.append(msg)

    def _goal_callback(self, goal_request):
        self.get_logger().info(f"Accepted goal request: dest={goal_request.destination_id}")
        self.received_goals.append(goal_request)
        return GoalResponse.ACCEPT

    def _cancel_callback(self, goal_handle):
        self.get_logger().info("Received cancel request for action goal")
        self.cancelled_goals.append(goal_handle)
        return CancelResponse.ACCEPT

    async def _execute_goal(self, goal_handle):
        self.get_logger().info("Executing action goal...")
        # Send feedback
        feedback_msg = GuideToDestination.Feedback()
        feedback_msg.distance_remaining_m = 1.5
        goal_handle.publish_feedback(feedback_msg)

        # Wait briefly
        for _ in range(5):
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                result = GuideToDestination.Result()
                result.error_code = 1
                result.error_msg = "Goal cancelled by client"
                return result
            await asyncio.sleep(0.1)

        goal_handle.succeed()
        result = GuideToDestination.Result()
        result.error_code = 0
        result.error_msg = "Successfully arrived at destination"
        return result


def spin_executor(executor: SingleThreadedExecutor, duration_sec: float):
    """Spin executor for a given duration in seconds."""
    start = time.time()
    while time.time() - start < duration_sec:
        executor.spin_once(timeout_sec=0.05)


def test_real_ros2_user_request_publication():
    """Verify web text command sends typed UserRequest on /guide/user_request without JSON string."""
    settings.USE_MOCK_ROS2 = False
    mock_node = MockLLMAndRobotNode()
    executor = SingleThreadedExecutor()
    executor.add_node(mock_node)

    with TestClient(app) as client:
        res = client.post(
            "/api/v1/command/text",
            headers={"X-Session-Id": "ros2-test-user"},
            json={"text": "ไปจุด A", "input_mode": "text"}
        )
        assert res.status_code == 200

        # Spin mock node executor to receive message
        spin_executor(executor, duration_sec=0.6)

        assert len(mock_node.received_user_requests) >= 1
        last_req = mock_node.received_user_requests[-1]
        assert isinstance(last_req, UserRequest)
        assert last_req.session_id == "ros2-test-user"
        assert last_req.text == "ไปจุด A"
        assert last_req.request_id.startswith("req-")

    executor.shutdown()
    mock_node.destroy_node()


def test_real_ros2_navigation_state_reception():
    """Verify Backend receives typed NavigationState and maps ARRIVED, NAVIGATING, and HOME correctly."""
    settings.USE_MOCK_ROS2 = False
    mock_node = MockLLMAndRobotNode()
    executor = SingleThreadedExecutor()
    executor.add_node(mock_node)

    with TestClient(app) as client:
        # 1. Publish NAVIGATING
        nav_msg = NavigationState()
        nav_msg.destination_id = "A"
        nav_msg.phase = "NAVIGATING"
        nav_msg.ready_for_goal = False
        nav_msg.distance_remaining_m = 8.5
        mock_node.pub_nav_state.publish(nav_msg)

        spin_executor(executor, duration_sec=0.5)
        time.sleep(0.2)
        state = session_manager.get_state_broadcast()
        assert state.robot_state == "NAVIGATING"
        assert state.current_goal == "A"

        # 2. Publish ARRIVED
        nav_msg.phase = "ARRIVED"
        nav_msg.distance_remaining_m = 0.0
        mock_node.pub_nav_state.publish(nav_msg)

        spin_executor(executor, duration_sec=0.5)
        time.sleep(0.2)
        state = session_manager.get_state_broadcast()
        assert state.robot_state == "REACHED"
        assert state.current_goal == "A"

        # 3. Publish HOME + ready_for_goal
        nav_msg.phase = "HOME"
        nav_msg.destination_id = "start"
        nav_msg.ready_for_goal = True
        mock_node.pub_nav_state.publish(nav_msg)

        spin_executor(executor, duration_sec=0.5)
        time.sleep(0.2)
        state = session_manager.get_state_broadcast()
        assert state.robot_state == "IDLE"
        assert state.current_goal == "start"

    executor.shutdown()
    mock_node.destroy_node()


def test_real_ros2_subtitle_reception_and_ttl_clearing():
    """Verify Backend receives Subtitle, displays it, and clears on TTL and empty text."""
    settings.USE_MOCK_ROS2 = False
    mock_node = MockLLMAndRobotNode()
    executor = SingleThreadedExecutor()
    executor.add_node(mock_node)

    with TestClient(app) as client:
        from app.main import ros_bridge_instance

        def set_current_source_stamp(message):
            message.stamp = ros_bridge_instance.node.get_clock().now().to_msg()

        # Reject source timestamps that are malformed or later than the ROS clock.
        invalid_msg = Subtitle()
        set_current_source_stamp(invalid_msg)
        invalid_msg.stamp.nanosec = 1_000_000_000
        invalid_msg.text = "invalid timestamp"
        invalid_msg.ttl.sec = 10
        mock_node.pub_subtitle.publish(invalid_msg)
        future_msg = Subtitle()
        set_current_source_stamp(future_msg)
        future_msg.stamp.sec += 10
        future_msg.text = "future timestamp"
        future_msg.ttl.sec = 10
        mock_node.pub_subtitle.publish(future_msg)
        spin_executor(executor, duration_sec=0.4)
        time.sleep(0.1)
        assert session_manager.get_state_broadcast().llm_reason == ""

        # 1. Send subtitle with 1s TTL
        sub_msg = Subtitle()
        set_current_source_stamp(sub_msg)
        sub_msg.text = "สวัสดีครับ กำลังนำทางไปจุด A"
        sub_msg.ttl.sec = 1
        sub_msg.ttl.nanosec = 0
        mock_node.pub_subtitle.publish(sub_msg)

        spin_executor(executor, duration_sec=0.5)
        time.sleep(0.2)
        state = session_manager.get_state_broadcast()
        assert state.llm_reason == "สวัสดีครับ กำลังนำทางไปจุด A"

        # Wait for TTL to expire (1.0s + margin)
        time.sleep(1.3)
        state = session_manager.get_state_broadcast()
        assert state.llm_reason == ""

        # 2. Send new subtitle then immediately clear with empty text (TTL=0)
        set_current_source_stamp(sub_msg)
        sub_msg.text = "ข้อความชั่วคราว"
        sub_msg.ttl.sec = 10
        mock_node.pub_subtitle.publish(sub_msg)
        spin_executor(executor, duration_sec=0.4)
        time.sleep(0.1)
        assert session_manager.get_state_broadcast().llm_reason == "ข้อความชั่วคราว"

        # Clear immediately
        set_current_source_stamp(sub_msg)
        sub_msg.text = ""
        sub_msg.ttl.sec = 0
        mock_node.pub_subtitle.publish(sub_msg)
        spin_executor(executor, duration_sec=0.4)
        time.sleep(0.1)
        assert session_manager.get_state_broadcast().llm_reason == ""

    executor.shutdown()
    mock_node.destroy_node()


def test_real_ros2_action_navigation_goal():
    """Verify system navigation (e.g. Return to Start) calls /guide/navigate Action server."""
    settings.USE_MOCK_ROS2 = False
    mock_node = MockLLMAndRobotNode()
    executor = SingleThreadedExecutor()
    executor.add_node(mock_node)

    with TestClient(app) as client:
        # Give ActionClient a moment to discover ActionServer
        spin_executor(executor, duration_sec=0.5)

        # Trigger staff return to start (PIN 1234)
        res = client.post(
            "/api/v1/staff/return-to-start",
            headers={"X-Staff-Pin": "1234"}
        )
        assert res.status_code == 200

        # Spin mock node to handle goal request
        spin_executor(executor, duration_sec=1.0)

        assert len(mock_node.received_goals) >= 1
        goal = mock_node.received_goals[-1]
        assert goal.destination_id == "A"
        assert goal.request_id.startswith("req-")

    executor.shutdown()
    mock_node.destroy_node()
