import os
"""Configuration module for Mobile Web Voice & Text Controller.
Uses pydantic-settings to load settings from environment variables and .env file.
Aligned with TurtleBot3 LLM Subtitle Architecture (intent_node & subtitle_node).
"""

from typing import List, Dict, Any
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
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
    START_BOOTH_ID: str = "start"
    DIRECT_ACTION_VALIDITY_SEC: float = 30.0

    @field_validator("DIRECT_ACTION_VALIDITY_SEC")
    @classmethod
    def validate_direct_action_validity(cls, value: float) -> float:
        import math
        if not math.isfinite(value) or value <= 0:
            raise ValueError("DIRECT_ACTION_VALIDITY_SEC must be finite and greater than zero")
        return value

    # Speech-to-Text (STT) Settings: "groq" | "openai" | "faster_whisper"
    STT_PROVIDER: str = "groq"
    STT_LANGUAGE: str = "th"
    GROQ_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # STT Domain Prompt / Lexicon Hints (Bilingual Thai-English Code-Switching for Whisper)
    STT_INITIAL_PROMPT: str = (
        "บทสนทนาสั่งงานหุ่นยนต์ TurtleBot3 ภาษาไทยผสมอังกฤษ (Code-Switching): "
        "จุด A, จุดเอ, A, เอ, จุด B, จุดบี, B, บี, จุด C, จุดซี, C, ซี, "
        "กลับจุดเริ่มต้น, กลับ start, จุดเริ่มต้น, start point. "
        "Go to point A, point B, point C, return to start."
    )

    # ROS 2 Integration Override
    USE_MOCK_ROS2: bool = False

    # Predefined Booth Locations for Quick Chips (Matching LLM destination_id)
    LOCATIONS: List[Dict[str, Any]] = Field(
        default_factory=lambda: [
            {
                "id": "A",
                "label": "📍 จุด A",
                "prompt": "ไปจุด A",
                "description": "พาไปจุด A",
                "icon": "code"
            },
            {
                "id": "B",
                "label": "📍 จุด B",
                "prompt": "ไปจุด B",
                "description": "พาไปจุด B",
                "icon": "calculator"
            },
            {
                "id": "C",
                "label": "📍 จุด C",
                "prompt": "ไปจุด C",
                "description": "พาไปจุด C",
                "icon": "map-pin"
            },
            {
                "id": "start",
                "label": "🏠 กลับจุดเริ่มต้น (จุด A)",
                "prompt": "กลับจุดเริ่มต้น",
                "description": "จุดรอสแกน QR Code หน้าบูธ",
                "icon": "home"
            },
            {
                "id": "wait",
                "label": "⏸️ ส่งคำขอรอ (ยังไม่รองรับ)",
                "prompt": "หยุดรอตรงนี้ก่อน",
                "description": "ส่งคำขอรอผ่านระบบแปลคำสั่ง (ยังไม่รองรับ)",
                "icon": "pause"
            }
        ]
    )


settings = Settings()
