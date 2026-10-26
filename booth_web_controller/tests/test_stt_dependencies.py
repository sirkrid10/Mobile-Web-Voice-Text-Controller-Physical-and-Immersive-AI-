"""Check that the installed SDK can initialize the real Groq STT adapter."""

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
