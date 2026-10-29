"""Speech-to-Text (STT) Engine Service.
Supports Groq Whisper API (ultra-low latency), OpenAI Whisper API,
local faster-whisper on WSL 2, and graceful fallback for offline booth testing.
"""

import os
import shutil
import tempfile
import asyncio
from fastapi import UploadFile

from app.config import settings


class STTUnavailableError(Exception):
    """The configured transcription provider could not produce a transcript."""


class STTService:
    def __init__(self):
        self.provider = settings.STT_PROVIDER.lower()
        self._groq_client = None
        self._openai_client = None
        self._local_model = None

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

    async def _preprocess_audio(self, input_path: str) -> str:
        """Pre-process audio using ffmpeg:
        - High-pass filter (cuts low-frequency rumble < STT_HIGHPASS_FREQ)
        - Low-pass filter (cuts high-frequency hiss > STT_LOWPASS_FREQ)
        - Dynamic audio normalization (equalizes volume without clipping across phone mics)
        - Resamples to 16kHz mono 16-bit PCM WAV (Whisper's optimal format)

        Returns path to processed WAV file, or input_path if ffmpeg is unavailable or fails.
        """
        if not getattr(settings, "STT_PREPROCESS_AUDIO", True):
            return input_path

        ffmpeg_bin = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
        if not ffmpeg_bin:
            return input_path

        filters = []
        if getattr(settings, "STT_HIGHPASS_FREQ", 0) > 0:
            filters.append(f"highpass=f={settings.STT_HIGHPASS_FREQ}")
        if getattr(settings, "STT_LOWPASS_FREQ", 0) > 0:
            filters.append(f"lowpass=f={settings.STT_LOWPASS_FREQ}")
        if getattr(settings, "STT_NORMALIZE_AUDIO", False):
            # Dynamic audio normalization: 75ms frame, 15dB max gain, 0.95 peak (-0.5 dBFS)
            filters.append("dynaudnorm=f=75:g=15:p=0.95")

        filter_arg = ",".join(filters) if filters else "anull"
        output_path = input_path + ".processed.wav"
        cmd = [
            ffmpeg_bin,
            "-y",
            "-i", input_path,
            "-af", filter_arg,
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            output_path
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await process.communicate()
            if process.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                print(f"[STTService] Audio successfully preprocessed -> {output_path} ({os.path.getsize(output_path)} bytes)")
                return output_path
            else:
                err_msg = stderr.decode("utf-8", errors="ignore") if stderr else "unknown"
                print(f"[STTService] ffmpeg audio processing returned code {process.returncode}: {err_msg[:200]}")
                return input_path
        except Exception as e:
            print(f"[STTService] Audio preprocessing encountered an error, falling back to original: {e}")
            return input_path

    def _save_debug_audio(self, raw_path: str, processed_path: str, raw_suffix: str) -> None:
        """Save copies of the raw uploaded audio and preprocessed audio for developer inspection."""
        if not getattr(settings, "STT_SAVE_DEBUG_AUDIO", False):
            return
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            debug_dir = getattr(settings, "STT_DEBUG_AUDIO_DIR", "debug_audio")
            if not os.path.isabs(debug_dir):
                debug_dir = os.path.join(base_dir, debug_dir)
            os.makedirs(debug_dir, exist_ok=True)

            # Copy raw upload
            if raw_path and os.path.exists(raw_path):
                raw_dest = os.path.join(debug_dir, f"latest_raw{raw_suffix}")
                shutil.copyfile(raw_path, raw_dest)

            # Copy exact audio fed to Whisper
            if processed_path and os.path.exists(processed_path):
                whisper_dest = os.path.join(debug_dir, "latest_whisper.wav")
                shutil.copyfile(processed_path, whisper_dest)
                print(f"[STTService] Debug audio saved: {whisper_dest} ({os.path.getsize(whisper_dest)} bytes)")
        except Exception as e:
            print(f"[STTService] Failed to save debug audio: {e}")

    async def transcribe_audio(self, audio_file: UploadFile) -> str:
        """Save uploaded audio (WebM/MP4/WAV) to a temporary file and transcribe with domain prompt."""
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

            # Pre-process audio if enabled and valid
            audio_to_transcribe = temp_path
            processed_path = await self._preprocess_audio(temp_path)
            if processed_path and processed_path != temp_path:
                audio_to_transcribe = processed_path

            # Save debug copies for developer inspection
            self._save_debug_audio(temp_path, audio_to_transcribe, suffix)

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
