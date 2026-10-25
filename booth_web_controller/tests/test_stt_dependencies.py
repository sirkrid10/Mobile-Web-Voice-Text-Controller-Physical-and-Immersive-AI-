"""Check that the installed SDK can initialize the real Groq STT adapter."""

import asyncio

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
