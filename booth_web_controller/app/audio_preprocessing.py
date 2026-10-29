"""Optional, bounded ffmpeg preprocessing for uploaded STT audio."""

import asyncio
from dataclasses import dataclass
import os
import shutil
import tempfile
import wave
from typing import Optional


OUTPUT_SAMPLE_RATE = 16_000
_TERMINATE_TIMEOUT_SEC = 1.0


@dataclass(frozen=True)
class PreprocessingResult:
    """A processed WAV path, or a reason to use the original upload."""

    processed_path: Optional[str]
    reason: str


def _is_valid_output(path: str) -> bool:
    try:
        with wave.open(path, "rb") as output:
            return (
                output.getnchannels() == 1
                and output.getsampwidth() == 2
                and output.getframerate() == OUTPUT_SAMPLE_RATE
                and output.getnframes() > 0
                and bool(output.readframes(1))
            )
    except (OSError, EOFError, wave.Error):
        return False


async def _terminate_and_reap(process, communication_task) -> None:
    """Stop and reap only the subprocess handle created for this request."""
    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass

        try:
            await asyncio.wait_for(process.wait(), timeout=_TERMINATE_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            await process.wait()

    if communication_task is not None:
        await communication_task


async def _cleanup_canceled_process(process, communication_task) -> None:
    cleanup = asyncio.create_task(_terminate_and_reap(process, communication_task))
    try:
        await asyncio.shield(cleanup)
    except asyncio.CancelledError:
        await cleanup
        raise


def _filter_chain(highpass_freq: int, lowpass_freq: int, normalize: bool) -> str:
    filters = []
    if highpass_freq:
        filters.append(f"highpass=f={highpass_freq}")
    if lowpass_freq:
        filters.append(f"lowpass=f={lowpass_freq}")
    if normalize:
        # gausssize is a smoothing-window length; maxgain is a linear gain factor.
        filters.append("dynaudnorm=framelen=75:gausssize=15:peak=0.95:maxgain=10")
    return ",".join(filters)


async def preprocess_audio(
    input_path: str,
    *,
    enabled: bool,
    highpass_freq: int,
    lowpass_freq: int,
    normalize: bool,
    timeout_sec: float,
) -> PreprocessingResult:
    """Convert/filter one upload; failures fall back to its original path.

    Cancellation is deliberately propagated after the owned ffmpeg process has
    been stopped and reaped. Callers own and must remove a successful output.
    """
    if not enabled:
        return PreprocessingResult(None, "disabled")

    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return PreprocessingResult(None, "ffmpeg_unavailable")

    fd, output_path = tempfile.mkstemp(prefix="stt-preprocess-", suffix=".wav")
    os.close(fd)
    process = None
    communication_task = None
    keep_output = False

    command = [
        ffmpeg_path,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-i",
        input_path,
    ]
    filters = _filter_chain(highpass_freq, lowpass_freq, normalize)
    if filters:
        command.extend(("-af", filters))
    command.extend((
        "-vn",
        "-ar", str(OUTPUT_SAMPLE_RATE),
        "-ac", "1",
        "-c:a", "pcm_s16le",
        "-f", "wav",
        output_path,
    ))

    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        communication_task = asyncio.create_task(process.communicate())
        done, _ = await asyncio.wait({communication_task}, timeout=timeout_sec)
        if not done:
            await _terminate_and_reap(process, communication_task)
            return PreprocessingResult(None, "ffmpeg_timeout")

        communication_task.result()
        if process.returncode != 0:
            return PreprocessingResult(None, "ffmpeg_nonzero_exit")
        if not _is_valid_output(output_path):
            return PreprocessingResult(None, "ffmpeg_invalid_output")

        keep_output = True
        return PreprocessingResult(output_path, "processed")
    except asyncio.CancelledError:
        if process is not None:
            await _cleanup_canceled_process(process, communication_task)
        raise
    except FileNotFoundError:
        return PreprocessingResult(None, "ffmpeg_unavailable")
    except Exception:
        if process is not None:
            try:
                await _terminate_and_reap(process, communication_task)
            except Exception:
                pass
        return PreprocessingResult(None, "ffmpeg_error")
    finally:
        if not keep_output:
            try:
                os.unlink(output_path)
            except OSError:
                pass
