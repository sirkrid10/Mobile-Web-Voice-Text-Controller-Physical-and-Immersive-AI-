"""Configuration module for Mobile Web Voice & Text Controller.
Uses pydantic-settings to load settings from environment variables and .env file.
"""

from typing import List, Dict, Any
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Server Network Configuration
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Staff Security
    STAFF_PIN: str = "1234"

    # Session & Auto-Return Timing (Seconds)
    INACTIVITY_TIMEOUT_SEC: int = 60
    WARNING_THRESHOLD_SEC: int = 15
    AUTO_RETURN_ENABLED: bool = True
    AUTO_RETURN_DELAY_SEC: int = 5
    START_BOOTH_ID: str = "START_BOOTH"

    # Speech-to-Text (STT) Settings: "groq" | "openai" | "faster_whisper"
    STT_PROVIDER: str = "groq"
    GROQ_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # STT Domain Prompt / Lexicon Hints
    STT_INITIAL_PROMPT: str = (
        "???????????????????? TurtleBot3: ??????? AI Exhibition, Presentation Area, "
        "Robotics Lab, Start Booth, ????????????. Take me to the AI exhibition, "
        "go to the presentation area, stop, wait."
    )

    # ROS 2 Integration Override
    USE_MOCK_ROS2: bool = False

    # Predefined Booth Locations for Quick Chips
    LOCATIONS: List[Dict[str, Any]] = Field(
        default_factory=lambda: [
            {
                "id": "AI_EXHIBITION",
                "label": "?? ????? AI Exhibition",
                "prompt": "?????????? AI Exhibition",
                "description": "???????????? AI & Robotics",
                "icon": "sparkles"
            },
            {
                "id": "PRESENTATION_AREA",
                "label": "?? ????? Presentation Area",
                "prompt": "?????????? Presentation Area",
                "description": "??????????????????????",
                "icon": "mic"
            },
            {
                "id": "ROBOTICS_LAB",
                "label": "?? ????? Robotics Lab",
                "prompt": "?????????? Robotics Lab",
                "description": "???????????????????",
                "icon": "cpu"
            },
            {
                "id": "START_BOOTH",
                "label": "?? ??????????????? (Start Point)",
                "prompt": "???????????????",
                "description": "???????? QR Code ???????",
                "icon": "home"
            },
            {
                "id": "WAIT_HERE",
                "label": "?? ???????????????? (Wait)",
                "prompt": "????????????????",
                "description": "?????????????????????????",
                "icon": "pause"
            }
        ]
    )


settings = Settings()
