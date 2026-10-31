from app import runtime
from app.routes import commands
from app.session_state import SessionError
import asyncio
from pathlib import Path
import tempfile

import pytest

from app import main, stt_service as stt_module
from app.audio_preprocessing import PreprocessingResult
from app.config import settings
from app.session_manager import SessionManager


class FakeUpload:
    content_type = "audio/webm;codecs=opus"
    filename = "visitor.webm"

    def __init__(self, data: bytes):
        self.data = data

    async def read(self):
        return self.data


def test_staff_toggle_does_not_change_upload_already_in_progress(monkeypatch):
    monkeypatch.setattr(settings, 'STT_PREPROCESS_AUDIO', False)
    service = stt_module.STTService()
    service.provider = 'groq'
    captured = []

    class Upload(FakeUpload):
        async def read(self):
            settings.STT_PREPROCESS_AUDIO = True
            return self.data

    async def preprocess(_path, **kwargs):
        captured.append(kwargs['enabled'])
        return PreprocessingResult(None, 'disabled')

    async def provider(_path):
        return 'ทดสอบ'

    monkeypatch.setattr(stt_module, 'preprocess_audio', preprocess)
    monkeypatch.setattr(service, '_transcribe_groq', provider)
    assert asyncio.run(service.transcribe_audio(Upload(b'first'))) == 'ทดสอบ'
    assert asyncio.run(service.transcribe_audio(FakeUpload(b'next'))) == 'ทดสอบ'
    assert captured == [False, True]


def test_disabled_preprocessing_sends_original_upload_and_cleans_it(monkeypatch):
    monkeypatch.setattr(settings, "STT_PREPROCESS_AUDIO", False)
    service = stt_module.STTService()
    service.provider = "groq"
    captured = []

    async def provider(path):
        captured.append((path, Path(path).read_bytes()))
        return "พาไปจุด A"

    monkeypatch.setattr(service, "_transcribe_groq", provider)
    assert asyncio.run(service.transcribe_audio(FakeUpload(b"original microphone bytes"))) == "พาไปจุด A"
    assert len(captured) == 1
    raw_path, raw_bytes = captured[0]
    assert raw_bytes == b"original microphone bytes"
    assert not Path(raw_path).exists()


def test_successful_preprocessing_uses_processed_file_and_cleans_both(monkeypatch):
    service = stt_module.STTService()
    service.provider = "groq"
    captured = []

    async def fake_preprocess(input_path, **_kwargs):
        fd, output_path = tempfile.mkstemp(prefix="test-processed-", suffix=".wav")
        import os
        os.close(fd)
        Path(output_path).write_bytes(b"processed wav bytes")
        captured.append((input_path, output_path))
        return PreprocessingResult(output_path, "processed")

    async def provider(path):
        captured.append(("provider", path, Path(path).read_bytes()))
        return "พาไปจุด B"

    monkeypatch.setattr(stt_module, "preprocess_audio", fake_preprocess)
    monkeypatch.setattr(service, "_transcribe_groq", provider)
    assert asyncio.run(service.transcribe_audio(FakeUpload(b"raw bytes"))) == "พาไปจุด B"

    raw_path, processed_path = captured[0]
    assert captured[1] == ("provider", processed_path, b"processed wav bytes")
    assert not Path(raw_path).exists()
    assert not Path(processed_path).exists()


@pytest.mark.parametrize("reason", ["ffmpeg_unavailable", "ffmpeg_timeout", "ffmpeg_invalid_output"])
def test_preprocessing_failure_falls_back_to_original_upload(monkeypatch, reason):
    service = stt_module.STTService()
    service.provider = "groq"
    captured = []

    async def failed_preprocess(_input_path, **_kwargs):
        return PreprocessingResult(None, reason)

    async def provider(path):
        captured.append((path, Path(path).read_bytes()))
        return "พาไปจุด C"

    monkeypatch.setattr(stt_module, "preprocess_audio", failed_preprocess)
    monkeypatch.setattr(service, "_transcribe_groq", provider)
    assert asyncio.run(service.transcribe_audio(FakeUpload(b"original after fallback"))) == "พาไปจุด C"
    assert len(captured) == 1
    raw_path, raw_bytes = captured[0]
    assert raw_bytes == b"original after fallback"
    assert not Path(raw_path).exists()


def test_provider_failure_cleans_raw_and_processed_files(monkeypatch):
    service = stt_module.STTService()
    service.provider = "groq"
    paths = []

    async def fake_preprocess(input_path, **_kwargs):
        fd, output_path = tempfile.mkstemp(prefix="test-provider-fail-", suffix=".wav")
        import os
        os.close(fd)
        Path(output_path).write_bytes(b"processed")
        paths.extend((input_path, output_path))
        return PreprocessingResult(output_path, "processed")

    async def fail_provider(_path):
        raise stt_module.STTUnavailableError("simulated provider failure")

    monkeypatch.setattr(stt_module, "preprocess_audio", fake_preprocess)
    monkeypatch.setattr(service, "_transcribe_groq", fail_provider)

    with pytest.raises(stt_module.STTUnavailableError, match="simulated provider failure"):
        asyncio.run(service.transcribe_audio(FakeUpload(b"raw")))
    assert len(paths) == 2
    assert all(not Path(path).exists() for path in paths)


def test_concurrent_uploads_keep_files_isolated_and_cleaned(monkeypatch):
    service = stt_module.STTService()
    service.provider = "groq"
    raw_and_processed = []
    provider_reads = []

    async def fake_preprocess(input_path, **_kwargs):
        raw = Path(input_path).read_bytes()
        fd, output_path = tempfile.mkstemp(prefix="test-isolated-", suffix=".wav")
        import os
        os.close(fd)
        Path(output_path).write_bytes(b"processed:" + raw)
        raw_and_processed.append((input_path, output_path))
        await asyncio.sleep(0)
        return PreprocessingResult(output_path, "processed")

    async def provider(path):
        await asyncio.sleep(0.01)
        provider_reads.append((path, Path(path).read_bytes()))
        return "ok"

    monkeypatch.setattr(stt_module, "preprocess_audio", fake_preprocess)
    monkeypatch.setattr(service, "_transcribe_groq", provider)

    async def run():
        return await asyncio.gather(
            service.transcribe_audio(FakeUpload(b"request-one")),
            service.transcribe_audio(FakeUpload(b"request-two")),
        )

    assert asyncio.run(run()) == ["ok", "ok"]
    assert len(raw_and_processed) == 2
    raw_paths = [raw for raw, _ in raw_and_processed]
    processed_paths = [processed for _, processed in raw_and_processed]
    assert len(set(raw_paths)) == 2
    assert len(set(processed_paths)) == 2
    assert {data for _, data in provider_reads} == {b"processed:request-one", b"processed:request-two"}
    assert all(not Path(path).exists() for path in raw_paths + processed_paths)


def test_cancellation_during_preprocessing_skips_provider_and_cleans_raw(monkeypatch):
    service = stt_module.STTService()
    service.provider = "groq"
    started = asyncio.Event()
    raw_paths = []
    provider_calls = []

    async def blocked_preprocess(input_path, **_kwargs):
        raw_paths.append(input_path)
        started.set()
        await asyncio.Event().wait()

    async def provider(_path):
        provider_calls.append(_path)
        return "unexpected"

    monkeypatch.setattr(stt_module, "preprocess_audio", blocked_preprocess)
    monkeypatch.setattr(service, "_transcribe_groq", provider)

    async def run():
        task = asyncio.create_task(service.transcribe_audio(FakeUpload(b"raw")))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert provider_calls == []
    assert len(raw_paths) == 1
    assert not Path(raw_paths[0]).exists()


def test_cancellation_during_provider_cleans_raw_and_processed_files(monkeypatch):
    service = stt_module.STTService()
    service.provider = "groq"
    paths = []
    provider_started = asyncio.Event()

    async def fake_preprocess(input_path, **_kwargs):
        fd, output_path = tempfile.mkstemp(prefix="test-provider-cancel-", suffix=".wav")
        import os
        os.close(fd)
        Path(output_path).write_bytes(b"processed")
        paths.extend((input_path, output_path))
        return PreprocessingResult(output_path, "processed")

    async def blocked_provider(_path):
        provider_started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(stt_module, "preprocess_audio", fake_preprocess)
    monkeypatch.setattr(service, "_transcribe_groq", blocked_provider)

    async def run():
        task = asyncio.create_task(service.transcribe_audio(FakeUpload(b"raw")))
        await provider_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    assert len(paths) == 2
    assert all(not Path(path).exists() for path in paths)


def test_voice_request_losing_session_during_stt_never_publishes(monkeypatch):
    class FakeBridge:
        def __init__(self):
            self.published = []

        def publish_user_transcript(self, **kwargs):
            self.published.append(kwargs)

    async def run():
        manager = SessionManager()
        manager.auto_return_enabled = False
        bridge = FakeBridge()
        started = asyncio.Event()
        resume = asyncio.Event()
        monkeypatch.setattr(runtime, 'session_manager', manager)
        monkeypatch.setattr(runtime, 'ros_bridge_instance', bridge)

        async def slow_transcription(_audio):
            started.set()
            await resume.wait()
            return "ไปจุด A"

        monkeypatch.setattr(runtime.stt_service, "transcribe_audio", slow_transcription)
        claim = await manager.claim("visitor-session")
        request = asyncio.create_task(commands.command_voice(
            FakeUpload(b"audio"),
            x_session_token=claim["session_token"],
            x_session_id="visitor-session",
        ))
        await started.wait()
        await manager.release_session(reason="user_disconnect")
        resume.set()
        with pytest.raises(SessionError) as error:
            await request
        assert error.value.status_code == 403
        assert bridge.published == []

    asyncio.run(run())
