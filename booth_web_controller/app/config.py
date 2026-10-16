import os
"""Configuration module for Mobile Web Voice & Text Controller.
Uses pydantic-settings to load settings from environment variables and .env file.
Aligned with TurtleBot3 LLM Subtitle Architecture (intent_node & subtitle_node).
"""

from typing import List, Dict, Any
from pydantic import Field
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

    # Speech-to-Text (STT) Settings: "groq" | "openai" | "faster_whisper"
    STT_PROVIDER: str = "groq"
    GROQ_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # STT Domain Prompt / Lexicon Hints (Bilingual Thai-English Code-Switching for Whisper)
    STT_INITIAL_PROMPT: str = (
        "บทสนทนาสั่งงานหุ่นยนต์ TurtleBot3 ภาษาไทยผสมอังกฤษ (Code-Switching): "
        "พาไปบูธ Computer Science, ช่วยพาไปบูธ CS, เดินไป booth 09 วิทยาการคอมพิวเตอร์, "
        "พาไปบูธ Mathematics and Statistics, ไปบูธ Math and Stat, booth 10 คณิตศาสตร์และสถิติ, "
        "กลับไปที่จุด Start, return to start point, หยุดรอตรงนี้, stop, wait here. "
        "Take me to Computer Science booth 09, Mathematics and Statistics booth 10, "
        "navigate to CS, go to Math and Stat, return to start."
    )

    # ROS 2 Integration Override
    USE_MOCK_ROS2: bool = False

    # Predefined Booth Locations for Quick Chips (Matching LLM destination_id)
    LOCATIONS: List[Dict[str, Any]] = Field(
        default_factory=lambda: [
            {
                "id": "booth_09",
                "label": "📍 บูธ 09: วิทยาการคอมพิวเตอร์",
                "prompt": "พาไปบูธคอมพิวเตอร์",
                "description": "บูธ 09 ภาควิชาวิทยาการคอมพิวเตอร์",
                "icon": "code"
            },
            {
                "id": "booth_10",
                "label": "📍 บูธ 10: คณิตศาสตร์และสถิติ",
                "prompt": "พาไปบูธคณิตศาสตร์และสถิติ",
                "description": "บูธ 10 ภาควิชาคณิตศาสตร์และสถิติ",
                "icon": "calculator"
            },
            {
                "id": "start",
                "label": "🏠 กลับจุดรอเริ่มต้น (Start Point)",
                "prompt": "กลับจุดเริ่มต้น",
                "description": "จุดรอสแกน QR Code หน้าบูธ",
                "icon": "home"
            },
            {
                "id": "wait",
                "label": "⏸️ หยุดรอตรงนี้ก่อน (Wait)",
                "prompt": "หยุดรอตรงนี้ก่อน",
                "description": "หยุดรอคำสั่งถัดไปชั่วคราว",
                "icon": "pause"
            }
        ]
    )


settings = Settings()
