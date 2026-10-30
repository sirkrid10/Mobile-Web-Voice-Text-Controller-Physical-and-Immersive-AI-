"""Speech-to-Text (STT) Engine Service.
Supports Groq Whisper API (ultra-low latency), OpenAI Whisper API,
local faster-whisper on WSL 2, and graceful fallback for offline booth testing.
"""

import os
import shutil
import tempfile
import asyncio
from fastapi import UploadFile

from app.audio_preprocessing import preprocess_audio
from app.config import settings


class STTUnavailableError(Exception):
    """The configured transcription provider could not produce a transcript."""


class STTService:
    def __init__(self):
        self.provider = settings.STT_PROVIDER.lower()
        self._groq_client = None
        self._openai_client = None
        self._local_model = None

    def preprocessing_status(self):
        return {
            'enabled': settings.STT_PREPROCESS_AUDIO,
            'ffmpeg_available': shutil.which('ffmpeg') is not None,
        }

    def _get_groq_client(self):
        if not self._groq_client:
            if not settings.GROQ_API_KEY or settings.GROQ_API_KEY == "your_groq_api_key_here":
                raise ValueError("GROQ_API_KEY is not configured in .env")
            from openai import AsyncOpenAI
            self._groq_client = AsyncOpenAI(
                base_url="https://api.groq.com/openai/v1",
                api_key=settings.GROQ_API_KEY
            )
        return self._groq_client

    def _get_openai_client(self):
        if not self._openai_client:
            if not settings.OPENAI_API_KEY or settings.OPENAI_API_KEY == "your_openai_api_key_here":
                raise ValueError("OPENAI_API_KEY is not configured in .env")
            from openai import AsyncOpenAI
            self._openai_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        return self._openai_client

    def _get_local_model(self):
        if not self._local_model:
            from faster_whisper import WhisperModel
            print("[STTService] Loading local faster-whisper (small, int8)...")
            self._local_model = WhisperModel("small", device="cpu", compute_type="int8")
        return self._local_model

    async def transcribe_audio(self, audio_file: UploadFile) -> str:
        """Save uploaded audio (WebM/MP4/WAV) to a temporary file and transcribe with domain prompt."""
        preprocess_enabled = settings.STT_PREPROCESS_AUDIO
        suffix = ".webm"
        if audio_file.content_type:
            if "mp4" in audio_file.content_type:
                suffix = ".mp4"
            elif "wav" in audio_file.content_type:
                suffix = ".wav"
            elif "ogg" in audio_file.content_type:
                suffix = ".ogg"
        elif audio_file.filename:
            _, ext = os.path.splitext(audio_file.filename)
            if ext:
                suffix = ext

        temp_path = None
        processed_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_path = temp_file.name
                content = await audio_file.read()
                temp_file.write(content)

            file_size = os.path.getsize(temp_path)
            print(f"[STTService] Processing audio file: {temp_path} ({file_size} bytes, type={audio_file.content_type}, provider={self.provider}, language={settings.STT_LANGUAGE})")

            try:
                preprocessing = await preprocess_audio(
                    temp_path,
                    enabled=preprocess_enabled,
                    highpass_freq=settings.STT_HIGHPASS_FREQ,
                    lowpass_freq=settings.STT_LOWPASS_FREQ,
                    normalize=settings.STT_NORMALIZE_AUDIO,
                    timeout_sec=settings.STT_PREPROCESS_TIMEOUT_SEC,
                )
                processed_path = preprocessing.processed_path
            except asyncio.CancelledError:
                raise
            except Exception:
                print("[STTService] Audio preprocessing failed unexpectedly; using original upload")
                preprocessing = None

            if processed_path:
                audio_to_transcribe = processed_path
                print("[STTService] Audio preprocessing completed; sending 16 kHz mono WAV")
            else:
                audio_to_transcribe = temp_path
                reason = preprocessing.reason if preprocessing else "preprocessing_error"
                if reason == "disabled":
                    print("[STTService] Audio preprocessing disabled; sending original upload")
                else:
                    print(f"[STTService] Audio preprocessing fallback ({reason}); sending original upload")

            # Route to configured provider
            if self.provider == "groq":
                return await self._transcribe_groq(audio_to_transcribe)
            elif self.provider == "openai":
                return await self._transcribe_openai(audio_to_transcribe)
            elif self.provider == "faster_whisper":
                return await self._transcribe_faster_whisper(audio_to_transcribe)
            else:
                raise STTUnavailableError("Unsupported transcription provider")

        except Exception as e:
            print(f"[STTService] STT transcription failed with provider '{self.provider}': {e}")
            if isinstance(e, STTUnavailableError):
                raise
            raise STTUnavailableError("Transcription provider failed") from e
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            if processed_path and processed_path != temp_path and os.path.exists(processed_path):
                try:
                    os.remove(processed_path)
                except Exception:
                    pass

    async def _transcribe_groq(self, file_path: str) -> str:
        try:
            client = self._get_groq_client()
            print(f"[STTService] Groq model={settings.STT_GROQ_MODEL}, language={settings.STT_LANGUAGE}")
            with open(file_path, "rb") as audio:
                transcription = await client.audio.transcriptions.create(
                    model=settings.STT_GROQ_MODEL,
                    file=audio,
                    language=settings.STT_LANGUAGE,
                    prompt=settings.STT_INITIAL_PROMPT,
                    temperature=0.0
                )
            result = transcription.text.strip()
            print(f"[STTService] Groq transcription: '{result}'")
            return result
        except Exception as e:
            raise STTUnavailableError("Groq transcription failed") from e

    async def _transcribe_openai(self, file_path: str) -> str:
        try:
            client = self._get_openai_client()
            with open(file_path, "rb") as audio:
                transcription = await client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio,
                    language=settings.STT_LANGUAGE,
                    prompt=settings.STT_INITIAL_PROMPT,
                    temperature=0.0
                )
            result = transcription.text.strip()
            print(f"[STTService] OpenAI transcription: '{result}'")
            return result
        except Exception as e:
            raise STTUnavailableError("OpenAI transcription failed") from e

    async def _transcribe_faster_whisper(self, file_path: str) -> str:
        def _run_model():
            model = self._get_local_model()
            segments, info = model.transcribe(
                file_path,
                language=settings.STT_LANGUAGE,
                initial_prompt=settings.STT_INITIAL_PROMPT,
                vad_filter=True
            )
            text = " ".join([s.text for s in segments]).strip()
            return text

        result = await asyncio.to_thread(_run_model)
        print(f"[STTService] faster-whisper transcription: '{result}'")
        return result


stt_service = STTService()
