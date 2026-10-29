import asyncio
import math
import os
from pathlib import Path
import shutil
import struct
import wave

import pytest

from app import audio_preprocessing
from app.config import Settings


def _write_valid_wav(path: str, payload: bytes = b"\x01\x00\x02\x00") -> None:
    with wave.open(path, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(payload)


def _run(input_path: str, **overrides):
    options = {
        "enabled": True,
        "highpass_freq": 100,
        "lowpass_freq": 7500,
        "normalize": False,
        "timeout_sec": 8.0,
    }
    options.update(overrides)
    return asyncio.run(audio_preprocessing.preprocess_audio(input_path, **options))


def test_preprocessing_is_disabled_by_default_and_does_not_discover_ffmpeg(monkeypatch):
    assert Settings(_env_file=None).STT_PREPROCESS_AUDIO is False

    def unexpected_discovery(_name):
        raise AssertionError("disabled preprocessing must not inspect ffmpeg")

    monkeypatch.setattr(audio_preprocessing.shutil, "which", unexpected_discovery)
    result = _run("input.webm", enabled=False)
    assert result.processed_path is None
    assert result.reason == "disabled"


def test_missing_ffmpeg_falls_back_without_subprocess(monkeypatch):
    monkeypatch.setattr(audio_preprocessing.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        audio_preprocessing.asyncio,
        "create_subprocess_exec",
        lambda *_args, **_kwargs: pytest.fail("must not spawn when ffmpeg is missing"),
    )

    result = _run("input.webm")
    assert result.processed_path is None
    assert result.reason == "ffmpeg_unavailable"


def test_success_builds_filtered_mono_16khz_wav(monkeypatch, tmp_path):
    commands = []

    class FakeProcess:
        returncode = 0

        def __init__(self, command):
            self.command = command

        async def communicate(self):
            _write_valid_wav(self.command[-1])
            return b"", b""

    async def fake_spawn(*command, **_kwargs):
        commands.append(command)
        return FakeProcess(command)

    monkeypatch.setattr(audio_preprocessing.shutil, "which", lambda _name: "/fake/ffmpeg")
    monkeypatch.setattr(audio_preprocessing.asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(audio_preprocessing.tempfile, "tempdir", str(tmp_path))

    result = _run("input.webm", normalize=True)

    assert result.reason == "processed"
    assert result.processed_path and Path(result.processed_path).is_file()
    command = commands[0]
    assert command[0] == "/fake/ffmpeg"
    assert "-nostdin" in command
    assert command[command.index("-i") + 1] == "input.webm"
    filters = command[command.index("-af") + 1]
    assert filters == (
        "highpass=f=100,lowpass=f=7500,"
        "dynaudnorm=framelen=75:gausssize=15:peak=0.95:maxgain=10"
    )
    assert command[command.index("-ar") + 1] == "16000"
    assert command[command.index("-ac") + 1] == "1"
    assert command[command.index("-c:a") + 1] == "pcm_s16le"
    with wave.open(result.processed_path, "rb") as output:
        assert (output.getnchannels(), output.getsampwidth(), output.getframerate()) == (1, 2, 16000)
    os.unlink(result.processed_path)


@pytest.mark.parametrize(
    "returncode,output_kind,reason",
    [
        (1, "valid", "ffmpeg_nonzero_exit"),
        (0, "empty", "ffmpeg_invalid_output"),
        (0, "invalid", "ffmpeg_invalid_output"),
    ],
)
def test_failed_or_invalid_output_is_removed_and_falls_back(
    monkeypatch, tmp_path, returncode, output_kind, reason
):
    output_paths = []

    class FakeProcess:
        def __init__(self, command):
            self.command = command
            self.returncode = returncode

        async def communicate(self):
            path = self.command[-1]
            output_paths.append(path)
            if output_kind == "valid":
                _write_valid_wav(path)
            elif output_kind == "invalid":
                Path(path).write_bytes(b"not a wav")
            return b"", b"deliberately not logged"

    async def fake_spawn(*command, **_kwargs):
        return FakeProcess(command)

    monkeypatch.setattr(audio_preprocessing.shutil, "which", lambda _name: "/fake/ffmpeg")
    monkeypatch.setattr(audio_preprocessing.asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(audio_preprocessing.tempfile, "tempdir", str(tmp_path))

    result = _run("input.webm")
    assert result.processed_path is None
    assert result.reason == reason
    assert len(output_paths) == 1
    assert not Path(output_paths[0]).exists()


def test_spawn_error_removes_partial_output_and_falls_back(monkeypatch, tmp_path):
    captured = []

    async def fail_spawn(*command, **_kwargs):
        captured.append(command[-1])
        raise FileNotFoundError("do not expose binary path")

    monkeypatch.setattr(audio_preprocessing.shutil, "which", lambda _name: "/fake/ffmpeg")
    monkeypatch.setattr(audio_preprocessing.asyncio, "create_subprocess_exec", fail_spawn)
    monkeypatch.setattr(audio_preprocessing.tempfile, "tempdir", str(tmp_path))

    result = _run("input.webm")
    assert result.reason == "ffmpeg_unavailable"
    assert not Path(captured[0]).exists()


def test_real_linux_ffmpeg_converts_pcm_when_available(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("Linux ffmpeg is not installed in this environment")

    input_path = tmp_path / "speech-like-tone.wav"
    sample_rate = 48_000
    with wave.open(str(input_path), "wb") as source:
        source.setnchannels(2)
        source.setsampwidth(2)
        source.setframerate(sample_rate)
        frames = bytearray()
        for index in range(sample_rate // 2):
            sample = int(3000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(struct.pack("<hh", sample, sample))
        source.writeframes(frames)

    result = _run(str(input_path), highpass_freq=100, lowpass_freq=7500)
    assert result.reason == "processed"
    assert result.processed_path
    try:
        with wave.open(result.processed_path, "rb") as output:
            assert (output.getnchannels(), output.getsampwidth(), output.getframerate()) == (1, 2, 16000)
            assert output.getnframes() > 0
            assert output.readframes(1)
    finally:
        os.unlink(result.processed_path)


class BlockingProcess:
    def __init__(self, command):
        self.command = command
        self.returncode = None
        self.terminated = asyncio.Event()
        self.terminate_calls = 0
        self.kill_calls = 0
        self.wait_calls = 0

    async def communicate(self):
        await self.terminated.wait()
        return b"", b""

    def terminate(self):
        self.terminate_calls += 1
        self.returncode = -15
        self.terminated.set()

    def kill(self):
        self.kill_calls += 1
        self.returncode = -9
        self.terminated.set()

    async def wait(self):
        self.wait_calls += 1
        await self.terminated.wait()
        return self.returncode


def test_timeout_terminates_reaps_and_removes_partial_output(monkeypatch, tmp_path):
    processes = []

    async def fake_spawn(*command, **_kwargs):
        process = BlockingProcess(command)
        processes.append(process)
        return process

    monkeypatch.setattr(audio_preprocessing.shutil, "which", lambda _name: "/fake/ffmpeg")
    monkeypatch.setattr(audio_preprocessing.asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(audio_preprocessing.tempfile, "tempdir", str(tmp_path))

    async def run():
        result = await audio_preprocessing.preprocess_audio(
            "input.webm", enabled=True, highpass_freq=100, lowpass_freq=7500,
            normalize=False, timeout_sec=0.01,
        )
        return result

    result = asyncio.run(run())
    process = processes[0]
    assert result.reason == "ffmpeg_timeout"
    assert process.terminate_calls == 1
    assert process.wait_calls == 1
    assert process.kill_calls == 0
    assert not Path(process.command[-1]).exists()


def test_cancellation_terminates_reaps_and_propagates_without_fallback(monkeypatch, tmp_path):
    processes = []
    created = None

    async def fake_spawn(*command, **_kwargs):
        process = BlockingProcess(command)
        processes.append(process)
        created.set()
        return process

    monkeypatch.setattr(audio_preprocessing.shutil, "which", lambda _name: "/fake/ffmpeg")
    monkeypatch.setattr(audio_preprocessing.asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(audio_preprocessing.tempfile, "tempdir", str(tmp_path))

    async def run():
        nonlocal created
        created = asyncio.Event()
        task = asyncio.create_task(audio_preprocessing.preprocess_audio(
            "input.webm", enabled=True, highpass_freq=100, lowpass_freq=7500,
            normalize=False, timeout_sec=5,
        ))
        await created.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(run())
    process = processes[0]
    assert process.terminate_calls == 1
    assert process.wait_calls == 1
    assert not Path(process.command[-1]).exists()


def test_timeout_kills_owned_process_when_terminate_does_not_stop_it(monkeypatch, tmp_path):
    processes = []

    class IgnoresTerminate(BlockingProcess):
        def terminate(self):
            self.terminate_calls += 1

    async def fake_spawn(*command, **_kwargs):
        process = IgnoresTerminate(command)
        processes.append(process)
        return process

    monkeypatch.setattr(audio_preprocessing.shutil, "which", lambda _name: "/fake/ffmpeg")
    monkeypatch.setattr(audio_preprocessing.asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(audio_preprocessing.tempfile, "tempdir", str(tmp_path))

    result = _run("input.webm", timeout_sec=0.01)
    process = processes[0]
    assert result.reason == "ffmpeg_timeout"
    assert process.terminate_calls == 1
    assert process.kill_calls == 1
    assert process.wait_calls == 2
    assert not Path(process.command[-1]).exists()


def test_communication_exception_stops_owned_process_and_falls_back(monkeypatch, tmp_path):
    processes = []

    class BrokenCommunicationProcess(BlockingProcess):
        async def communicate(self):
            raise RuntimeError("fake ffmpeg communication error")

    async def fake_spawn(*command, **_kwargs):
        process = BrokenCommunicationProcess(command)
        processes.append(process)
        return process

    monkeypatch.setattr(audio_preprocessing.shutil, "which", lambda _name: "/fake/ffmpeg")
    monkeypatch.setattr(audio_preprocessing.asyncio, "create_subprocess_exec", fake_spawn)
    monkeypatch.setattr(audio_preprocessing.tempfile, "tempdir", str(tmp_path))

    result = _run("input.webm")
    process = processes[0]
    assert result.processed_path is None
    assert result.reason == "ffmpeg_error"
    assert process.terminate_calls == 1
    assert process.wait_calls == 1
    assert not Path(process.command[-1]).exists()


@pytest.mark.parametrize(
    "values",
    [
        {"STT_PREPROCESS_TIMEOUT_SEC": 0},
        {"STT_PREPROCESS_TIMEOUT_SEC": float("inf")},
        {"STT_PREPROCESS_TIMEOUT_SEC": float("nan")},
        {"STT_HIGHPASS_FREQ": -1},
        {"STT_LOWPASS_FREQ": 8000},
        {"STT_HIGHPASS_FREQ": 8000},
        {"STT_HIGHPASS_FREQ": 500, "STT_LOWPASS_FREQ": 500},
    ],
)
def test_preprocessing_config_rejects_unsupported_values(values):
    with pytest.raises(ValueError):
        Settings(_env_file=None, **values)


def test_preprocessing_config_accepts_zero_to_disable_each_filter():
    config = Settings(_env_file=None, STT_HIGHPASS_FREQ=0, STT_LOWPASS_FREQ=0)
    assert config.STT_HIGHPASS_FREQ == 0
    assert config.STT_LOWPASS_FREQ == 0
