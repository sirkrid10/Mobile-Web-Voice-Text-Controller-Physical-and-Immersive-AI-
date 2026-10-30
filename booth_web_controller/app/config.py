import os
"""Configuration module for Mobile Web Voice & Text Controller.
Uses pydantic-settings to load settings from environment variables and .env file.
Aligned with TurtleBot3 LLM Subtitle Architecture (intent_node & subtitle_node).
"""

from typing import List, Dict, Any
from pathlib import Path
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from app.destinations import DESTINATION_IDS, STATION_SPEECH_HINT, visitor_locations


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
    DIALOGUE_HISTORY_PATH: str = ''
    MANAGE_AGENT_NODES: bool = False
    AGENT_WORKSPACE: str = str(Path(__file__).resolve().parents[3] / 'turtlebot-llm')
    AGENT_CLOCK_SKEW_SEC: float = Field(0.6, ge=0, le=0.6, allow_inf_nan=False)

    # Cloudflare Quick Tunnel & Static QR Automation (Stage 2)
    ENABLE_TUNNEL: bool = False
    WORKER_STATIC_URL: str = ""
    CLOUDFLARE_API_TOKEN: str = ""
    CLOUDFLARE_ACCOUNT_ID: str = ""
    CLOUDFLARE_KV_NAMESPACE_ID: str = ""
    CLOUDFLARE_KV_KEY: str = "robot_url"

    # Session & Auto-Return Timing (Seconds)
    INACTIVITY_TIMEOUT_SEC: int = 120
    WARNING_THRESHOLD_SEC: int = 15
    AUTO_RETURN_ENABLED: bool = True
    AUTO_RETURN_DELAY_SEC: int = 5
    START_BOOTH_ID: str = "D"
    DIRECT_ACTION_VALIDITY_SEC: float = 30.0

    @field_validator("START_BOOTH_ID")
    @classmethod
    def validate_start_booth(cls, value: str) -> str:
        if value not in DESTINATION_IDS:
            raise ValueError("START_BOOTH_ID must use the Robot A/B/C/D contract; set D for return")
        return value

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
    STT_GROQ_MODEL: str = "whisper-large-v3"
    GROQ_API_KEY: str = ""
    OPENAI_API_KEY: str = ""

    # Optional Linux ffmpeg preprocessing; keep disabled until real-audio A/B testing.
    STT_PREPROCESS_AUDIO: bool = False
    STT_HIGHPASS_FREQ: int = Field(100, ge=0, lt=8000)
    STT_LOWPASS_FREQ: int = Field(7500, ge=0, lt=8000)
    STT_NORMALIZE_AUDIO: bool = False
    STT_PREPROCESS_TIMEOUT_SEC: float = Field(8.0, gt=0, le=30, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_stt_preprocessing(self):
        if (
            self.STT_HIGHPASS_FREQ > 0
            and self.STT_LOWPASS_FREQ > 0
            and self.STT_HIGHPASS_FREQ >= self.STT_LOWPASS_FREQ
        ):
            raise ValueError("STT_HIGHPASS_FREQ must be lower than STT_LOWPASS_FREQ when both filters are enabled")
        return self

    # STT Domain Prompt / Lexicon Hints (Bilingual Thai-English Code-Switching for Whisper)
    STT_INITIAL_PROMPT: str = STATION_SPEECH_HINT

    @field_validator('STT_INITIAL_PROMPT')
    @classmethod
    def include_station_names(cls, value: str) -> str:
        # Existing .env hints must not hide newly added stations/names.
        return value if STATION_SPEECH_HINT in value else value + ' ' + STATION_SPEECH_HINT


    # ROS 2 Integration Override
    USE_MOCK_ROS2: bool = False

    # Predefined Booth Locations for Quick Chips (Matching LLM destination_id)
    LOCATIONS: List[Dict[str, Any]] = Field(default_factory=visitor_locations)


settings = Settings()
