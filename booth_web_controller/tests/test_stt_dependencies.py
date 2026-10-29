"""Check that the installed SDK can initialize the real Groq STT adapter."""

import os
import asyncio
from types import SimpleNamespace

import httpx
from openai import AsyncOpenAI
import pytest

from app.config import settings
from app.stt_service import STTService


def test_groq_stt_sdk_initializes_without_network(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "offline-sdk-smoke-test")

    async def check_client():
        service = STTService()
        client = service._get_groq_client()
        try:
            assert str(client.base_url) == "https://api.groq.com/openai/v1/"
            assert callable(client.audio.transcriptions.create)
        finally:
            await client.close()

    asyncio.run(check_client())


class FakeThaiAudio:
    content_type = "audio/webm;codecs=opus"
    filename = "thai-request.webm"

    async def read(self):
        return b"offline audio fixture"


@pytest.mark.parametrize("provider", ["groq", "openai"])
@pytest.mark.parametrize("language", ["th", "en"])
def test_cloud_transcription_sends_configured_language(monkeypatch, provider, language):
    monkeypatch.setattr(settings, "STT_LANGUAGE", language)
    async def check_request():
        calls = []

        async def respond(request):
            body = await request.aread()
            calls.append(body)
            assert ('name="language"\r\n\r\n' + language + '\r\n').encode() in body
            expected_model = "whisper-large-v3" if provider == "groq" else "whisper-1"
            assert ('name="model"\r\n\r\n' + expected_model + '\r\n').encode() in body
            return httpx.Response(200, json={"text": "พาไปจุด A"})

        client = AsyncOpenAI(
            api_key="offline-test-key",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
            max_retries=0,
        )
        service = STTService()
        service.provider = provider
        setattr(service, "_groq_client" if provider == "groq" else "_openai_client", client)
        try:
            assert await service.transcribe_audio(FakeThaiAudio()) == "พาไปจุด A"
            assert len(calls) == 1
        finally:
            await client.close()

    asyncio.run(check_request())


@pytest.mark.parametrize("language", ["th", "en"])
def test_local_transcription_sends_configured_language(monkeypatch, language):
    monkeypatch.setattr(settings, "STT_LANGUAGE", language)
    calls = []

    def transcribe(_path, **kwargs):
        calls.append(kwargs)
        return [SimpleNamespace(text="พาไปจุด A")], SimpleNamespace()

    service = STTService()
    service.provider = "faster_whisper"
    service._local_model = SimpleNamespace(transcribe=transcribe)
    assert asyncio.run(service.transcribe_audio(FakeThaiAudio())) == "พาไปจุด A"
    assert calls[0].get("language") == language


def test_preprocess_audio_disabled(monkeypatch):
    monkeypatch.setattr(settings, "STT_PREPROCESS_AUDIO", False)
    service = STTService()
    res = asyncio.run(service._preprocess_audio("sample_test.webm"))
    assert res == "sample_test.webm"


def test_preprocess_audio_fallback_when_ffmpeg_missing(monkeypatch):
    import shutil
    monkeypatch.setattr(settings, "STT_PREPROCESS_AUDIO", True)
    monkeypatch.setattr(shutil, "which", lambda _cmd: None)
    service = STTService()
    res = asyncio.run(service._preprocess_audio("sample_test.webm"))
    assert res == "sample_test.webm"


def test_preprocess_audio_filters_configuration(monkeypatch):
    import tempfile
    monkeypatch.setattr(settings, "STT_PREPROCESS_AUDIO", True)
    monkeypatch.setattr(settings, "STT_HIGHPASS_FREQ", 120)
    monkeypatch.setattr(settings, "STT_LOWPASS_FREQ", 7000)
    monkeypatch.setattr(settings, "STT_NORMALIZE_AUDIO", True)

    executed_cmds = []

    async def fake_subprocess(*cmd, **_kwargs):
        executed_cmds.append(cmd)
        class FakeProcess:
            returncode = 0
            async def communicate(self):
                # write fake output file so os.path.exists passes
                with open(cmd[-1], "wb") as f:
                    f.write(b"RIFF....WAVEfmt ")
                return b"", b""
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
    service = STTService()

    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
        temp_input = f.name
        f.write(b"fake data")

    try:
        out = asyncio.run(service._preprocess_audio(temp_input))
        assert out == temp_input + ".processed.wav"
        assert len(executed_cmds) == 1
        cmd = executed_cmds[0]
        # Verify audio filters
        af_idx = cmd.index("-af")
        filter_str = cmd[af_idx + 1]
        assert "highpass=f=120" in filter_str
        assert "lowpass=f=7000" in filter_str
        assert "dynaudnorm" in filter_str
        # Verify 16kHz mono format
        assert "-ar" in cmd and cmd[cmd.index("-ar") + 1] == "16000"
        assert "-ac" in cmd and cmd[cmd.index("-ac") + 1] == "1"
        assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "pcm_s16le"
    finally:
        if os.path.exists(temp_input):
            os.remove(temp_input)
        if os.path.exists(temp_input + ".processed.wav"):
            os.remove(temp_input + ".processed.wav")


def test_preprocess_audio_real_ffmpeg_execution():
    import shutil
    import subprocess
    import tempfile
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not available")

    service = STTService()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tone_path = f.name

    # Generate 1-second 440Hz test audio tone with ffmpeg
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", tone_path],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )

    try:
        processed = asyncio.run(service._preprocess_audio(tone_path))
        assert processed != tone_path
        assert os.path.exists(processed)
        assert os.path.getsize(processed) > 0
        assert processed.endswith(".processed.wav")
    finally:
        if os.path.exists(tone_path):
            os.remove(tone_path)
        if os.path.exists(tone_path + ".processed.wav"):
            os.remove(tone_path + ".processed.wav")
