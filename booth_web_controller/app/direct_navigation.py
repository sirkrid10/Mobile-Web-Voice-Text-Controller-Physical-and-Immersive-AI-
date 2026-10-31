"""Own direct Staff/auto-return Action dispatch and result handling."""

import secrets
from typing import Optional

from app.config import settings
from app.models import DirectActionOutcome


class DirectNavigation:
    def send_navigation_goal(self, destination_id: str, request_id: Optional[str] = None, source: str = "web_controller"):
        """Send ROS 2 Action Goal to /guide/navigate (GuideToDestination)."""
        req_id = request_id or f"req-{secrets.token_hex(4)}"
        context = {"request_id": req_id, "source": source, "destination_id": destination_id}
        self._latest_action_request_id = req_id
        self.session_manager.record_action_outcome(DirectActionOutcome(**context, outcome="sending"))

        if not self.node.action_client_navigate.wait_for_server(timeout_sec=2.0):
            self.node.get_logger().error("Action server /guide/navigate is not available!")
            self._record_action(DirectActionOutcome(**context, outcome="unavailable", error_msg="Action server unavailable"))
            return

        goal_msg = self.GuideToDestination.Goal()
        goal_msg.request_id = req_id
        goal_msg.destination_id = destination_id
        goal_msg.valid_until = (
            self.node.get_clock().now() + self.Duration(seconds=settings.DIRECT_ACTION_VALIDITY_SEC)
        ).to_msg()

        self.node.get_logger().info(f"Sending Action Goal to /guide/navigate: req_id={req_id}, dest={destination_id}")

        send_future = self.node.action_client_navigate.send_goal_async(
            goal_msg,
            feedback_callback=self._on_action_feedback
        )
        send_future.add_done_callback(lambda future: self._on_goal_response(future, context))

    def _on_action_feedback(self, feedback_msg):
        dist = feedback_msg.feedback.distance_remaining_m
        self.node.get_logger().debug(f"Action /guide/navigate feedback: distance_remaining={dist:.2f}m")

    def _record_action(self, outcome: DirectActionOutcome):
        self.loop.call_soon_threadsafe(self.session_manager.record_action_outcome, outcome)

    def _on_goal_response(self, future, context):
        try:
            goal_handle = future.result()
        except Exception as exc:
            self.node.get_logger().error(f"Action send failed: {exc}")
            self._record_action(DirectActionOutcome(**context, outcome="transport_error", error_msg=str(exc)))
            return
        if not goal_handle.accepted:
            self.node.get_logger().warn("Action Goal rejected by /guide/navigate server!")
            self._record_action(DirectActionOutcome(**context, outcome="rejected"))
            return

        self.node.get_logger().info("Action Goal accepted by /guide/navigate server.")
        if self._latest_action_request_id == context["request_id"]:
            self.active_goal_handle = goal_handle
            self._active_goal_request_id = context["request_id"]
        self._record_action(DirectActionOutcome(**context, outcome="accepted"))

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(lambda future: self._on_goal_result(future, context))

    def _on_goal_result(self, future, context):
        try:
            result_wrapper = future.result()
        except Exception as exc:
            self.node.get_logger().error(f"Action result failed: {exc}")
            self._record_action(DirectActionOutcome(**context, outcome="transport_error", error_msg=str(exc)))
            if self._active_goal_request_id == context["request_id"]:
                self.active_goal_handle = None
                self._active_goal_request_id = None
            return
        status = result_wrapper.status
        result = result_wrapper.result
        self.node.get_logger().info(
            f"Action /guide/navigate finished: status={status}, error_code={result.error_code}, msg='{result.error_msg}'"
        )
        if status == self.GoalStatus.STATUS_SUCCEEDED:
            outcome = "succeeded" if result.error_code == 0 else "failed"
        elif status == self.GoalStatus.STATUS_ABORTED:
            outcome = "aborted"
        elif status == self.GoalStatus.STATUS_CANCELED:
            outcome = "canceled"
        else:
            outcome = "failed"
        self._record_action(DirectActionOutcome(
            **context,
            outcome=outcome,
            ros_status=status,
            error_code=result.error_code,
            error_msg=result.error_msg,
        ))
        if self._active_goal_request_id == context["request_id"]:
            self.active_goal_handle = None
            self._active_goal_request_id = None

    def cancel_navigation_goal(self):
        """Cancel active Action goal using ROS Action cancel mechanism."""
        if self.active_goal_handle is not None:
            self.node.get_logger().info("Cancelling active /guide/navigate Action goal...")
            self.active_goal_handle.cancel_goal_async()
            self.active_goal_handle = None
            self._active_goal_request_id = None
