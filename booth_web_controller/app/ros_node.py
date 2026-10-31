"""Create ROS subscriptions and marshal callbacks to the asyncio owner loop."""

import math, time

from app.models import IntentOutcome, IntentDispatchOutcome, RosStamp


def map_navigation_state(phase: str, ready_for_goal: bool, error_code: int) -> str:
    phase = (phase or "").upper()
    if error_code != 0 or phase == "FAILED":
        return "FAILED"
    if phase in ("NAVIGATING", "RETURNING_HOME"):
        return "NAVIGATING"
    if phase == "ARRIVED":
        return "REACHED"
    if phase in ("READY", "HOME"):
        return "IDLE" if ready_for_goal else "NOT_READY"
    if phase == "NOT_READY":
        return "NOT_READY"
    if phase == "CANCELED":
        return "STOPPED"
    return "UNKNOWN"


def create_bridge_node(outer):
    from rclpy.node import Node
    from rclpy.action import ActionClient
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, HistoryPolicy
    from ai_interfaces.msg import UserRequest, NavigationState, Subtitle, IntentResult, IntentDispatch
    from ai_interfaces.action import GuideToDestination
    from std_msgs.msg import Bool
    from geometry_msgs.msg import Twist

    # Contract QoS: Reliable, Volatile, Depth 10
    qos_profile = QoSProfile(
        reliability=ReliabilityPolicy.RELIABLE,
        durability=DurabilityPolicy.VOLATILE,
        history=HistoryPolicy.KEEP_LAST,
        depth=10
    )

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

            # 6. Subscriber: /guide/intent_result (IntentResult)
            self.sub_intent_result = self.create_subscription(
                IntentResult,
                '/guide/intent_result',
                self._on_intent_result,
                qos_profile
            )
            self.sub_intent_dispatch = self.create_subscription(
                IntentDispatch, '/guide/intent_dispatch',
                self._on_intent_dispatch, qos_profile,
            )

        def _on_intent_dispatch(self, msg: IntentDispatch):
            statuses = {IntentDispatch.SENT: "sent", IntentDispatch.UNKNOWN: "unknown"}
            if msg.status not in statuses or msg.stamp.sec <= 0 or not 0 <= msg.stamp.nanosec < 1_000_000_000:
                return
            outcome = IntentDispatchOutcome(
                request_id=msg.request_id, session_id=msg.session_id,
                stamp=RosStamp(sec=msg.stamp.sec, nanosec=msg.stamp.nanosec),
                destination_id=msg.destination_id, status=statuses[msg.status],
            )
            outer.loop.call_soon_threadsafe(outer.session_manager.record_intent_dispatch, outcome)

        def _on_navigation_state(self, msg: NavigationState):
            """Handle /robot/navigation_state updates directly from NavigationState."""
            try:
                phase = (msg.phase or "").upper()
                dest_id = msg.destination_id
                ready_for_goal = msg.ready_for_goal
                dist = msg.distance_remaining_m
                error_code = msg.error_code

                self.get_logger().info(
                    f"[/robot/navigation_state] phase={phase}, dest={dest_id}, ready={ready_for_goal}, dist={dist:.2f}m"
                )

                mapped_state = map_navigation_state(phase, ready_for_goal, error_code)

                def _sync():
                    outer._robot_observation = {
                        'robot_received_at': time.time(),
                        'robot_source_at': msg.stamp.sec + msg.stamp.nanosec / 1e9
                            if msg.stamp.sec > 0 and 0 <= msg.stamp.nanosec < 1_000_000_000 else None,
                        'robot_phase': phase, 'robot_ready_for_goal': ready_for_goal,
                        'robot_error_code': error_code,
                    }
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
                if not (0 <= msg.stamp.nanosec < 1_000_000_000):
                    return
                if not (0 <= msg.ttl.nanosec < 1_000_000_000) or msg.ttl.sec < 0:
                    return
                stamp_sec = msg.stamp.sec + msg.stamp.nanosec * 1e-9
                ttl_sec = msg.ttl.sec + msg.ttl.nanosec * 1e-9
                text = (msg.text or "").strip()
                if stamp_sec <= 0 or ttl_sec < 0:
                    return
                deadline = stamp_sec + ttl_sec
                if not math.isfinite(deadline):
                    return
                outer.loop.call_soon_threadsafe(outer._accept_subtitle, stamp_sec, deadline, text,
                                                msg.request_id, msg.observation_id)
            except Exception as e:
                self.get_logger().error(f"Error handling /vr/subtitle: {e}")

        def _on_intent_result(self, msg: IntentResult):
            try:
                statuses = {
                    IntentResult.NAVIGATE: "NAVIGATE",
                    IntentResult.CLARIFY: "CLARIFY",
                    IntentResult.UNSUPPORTED: "UNSUPPORTED",
                    IntentResult.FAILED: "FAILED",
                }
                status = statuses.get(msg.status)
                if status is None:
                    self.get_logger().warning(f"Discarding unknown IntentResult status: {msg.status}")
                    return
                outcome = IntentOutcome(
                    request_id=msg.request_id,
                    session_id=msg.session_id,
                    stamp=RosStamp(sec=msg.stamp.sec, nanosec=msg.stamp.nanosec),
                    status=status,
                    destination_id=msg.destination_id,
                    message=msg.message,
                    error_code=msg.error_code,
                )
                outer.loop.call_soon_threadsafe(outer.session_manager.record_intent_result, outcome)
            except Exception as e:
                self.get_logger().error(f"Error handling /guide/intent_result: {e}")

    return BoothWebBridgeNode()
