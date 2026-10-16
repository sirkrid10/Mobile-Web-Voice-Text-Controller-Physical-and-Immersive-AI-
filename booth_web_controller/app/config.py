import os
"""Configuration module for Mobile Web Voice & Text Controller.
Uses pydantic-settings to load settings from environment variables and .env file.
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
    START_BOOTH_ID: str = "START_BOOTH"

    # Speech-to-Text (STT) Settings: "groq" | "openai" | "faster_whisper"
    STT_PROVIDER: str = "groq"
    GROQ_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # STT Domain Prompt / Lexicon Hints
    STT_INITIAL_PROMPT: str = (
        "คำสั่งควบคุมหุ่นยนต์ TurtleBot3: พาไปที่ AI Exhibition, Presentation Area, "
        "Robotics Lab, Start Booth, หยุดรอตรงนี้. Take me to the AI exhibition, "
        "go to the presentation area, stop, wait."
    )

    # ROS 2 Integration Override
    USE_MOCK_ROS2: bool = False

    # Predefined Booth Locations for Quick Chips
    LOCATIONS: List[Dict[str, Any]] = Field(
        default_factory=lambda: [
            {
                "id": "AI_EXHIBITION",
                "label": "📍 ไปโซน AI Exhibition",
                "prompt": "พาไปที่โซน AI Exhibition",
                "description": "บูธแสดงผลงาน AI & Robotics",
                "icon": "sparkles"
            },
            {
                "id": "PRESENTATION_AREA",
                "label": "🎤 ไปจุด Presentation Area",
                "prompt": "พาไปที่จุด Presentation Area",
                "description": "เวทีบรรยายและสาธิตหลัก",
                "icon": "mic"
            },
            {
                "id": "ROBOTICS_LAB",
                "label": "🤖 ไปโซน Robotics Lab",
                "prompt": "พาไปที่โซน Robotics Lab",
                "description": "พื้นที่แล็บหุ่นยนต์",
                "icon": "cpu"
            },
            {
                "id": "START_BOOTH",
                "label": "🏠 กลับจุดเริ่มต้น (Start Point)",
                "prompt": "กลับจุดเริ่มต้น",
                "description": "ป้ายสแกน QR Code หน้าบูธ",
                "icon": "home"
            },
            {
                "id": "WAIT_HERE",
                "label": "⏸️ หยุดรอตรงนี้ก่อน (Wait)",
                "prompt": "หยุดรอตรงนี้ก่อน",
                "description": "หยุดรอคำสั่งถัดไปชั่วคราว",
                "icon": "pause"
            }
        ]
    )


settings = Settings()
