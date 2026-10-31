"""Define transport operations shared by real and mock ROS bridges."""

from abc import ABC, abstractmethod
from typing import Optional, Dict

from app.subtitle_lifecycle import SubtitleLifecycle
from app.subtitle_mode import SubtitleModeError


class BaseROS2Bridge(SubtitleLifecycle, ABC):
    async def existing_agent_responds(self, name):
        return False

    def robot_observation(self):
        return dict(getattr(self, '_robot_observation', {}))

    async def inspect_connections(self):
        return {'mode': 'mock', 'intent': 'unavailable', 'subtitle': 'unavailable'}

    @abstractmethod
    def publish_user_transcript(self, request_id: str, session_id: str, input_mode: str, text: str):
        """Publish visitor request to /guide/user_request for LLM intent parsing."""
        pass

    @abstractmethod
    def publish_high_level_action(self, action: str, target: str, explanation: str, source: str = "web_controller"):
        """Trigger direct navigation command (e.g. Return to Start, Staff override) via Action."""
        pass

    @abstractmethod
    def send_navigation_goal(self, destination_id: str, request_id: Optional[str] = None, source: str = "web_controller"):
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

    async def read_subtitle_mode(self):
        raise SubtitleModeError(503, 'Subtitle mode requires a running subtitle node and real ROS bridge')

    async def set_subtitle_mode(self, mode):
        raise SubtitleModeError(503, 'Subtitle mode requires a running subtitle node and real ROS bridge')

    @abstractmethod
    def shutdown(self):
        """Gracefully release bridge resources."""
        pass
