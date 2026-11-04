from __future__ import annotations

from array import array
from dataclasses import dataclass
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
import wave


class SpeechTranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class SpeechTranscription:
    transcript: str
    confidence: float | None


def _write_pcm_wav(path: Path, pcm_s16le: bytes, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(pcm_s16le)


def prepare_pcm_for_speech(pcm_s16le: bytes, sample_rate: int) -> bytes:
    """Trim quiet padding and raise low board-microphone speech to a useful level."""

    if not pcm_s16le or sample_rate <= 0 or len(pcm_s16le) % 2:
        return pcm_s16le

    samples = array("h")
    samples.frombytes(pcm_s16le)
    if sys.byteorder != "little":
        samples.byteswap()
    if len(samples) < sample_rate:
        return pcm_s16le

    chunk_size = max(sample_rate // 50, 1)
    chunks = []
    for start in range(0, len(samples), chunk_size):
        block = samples[start : start + chunk_size]
        if not block:
            continue
        square_sum = sum(sample * sample for sample in block)
        rms = math.isqrt(square_sum // len(block))
        peak = max(abs(sample) for sample in block)
        chunks.append((start, start + len(block), rms, peak))

    # The first packets contain a repeatable microphone-start transient, so do
    # not use them to estimate the room noise floor or voice boundaries.
    startup_samples = min(len(samples), sample_rate // 5)
    stable_chunks = [chunk for chunk in chunks if chunk[0] >= startup_samples]
    if not stable_chunks:
        return pcm_s16le
    sorted_rms = sorted(chunk[2] for chunk in stable_chunks)
    noise_floor = sorted_rms[max(0, len(sorted_rms) // 4)]
    rms_threshold = max(450, noise_floor * 2)
    peak_threshold = max(1400, noise_floor * 5)
    active = [
        chunk
        for chunk in stable_chunks
        if chunk[2] >= rms_threshold or chunk[3] >= peak_threshold
    ]
    if not active:
        return pcm_s16le

    padding_before = sample_rate * 3 // 10
    padding_after = sample_rate * 6 // 10
    start = max(startup_samples, active[0][0] - padding_before)
    end = min(len(samples), active[-1][1] + padding_after)
    prepared = samples[start:end]
    if len(prepared) < sample_rate // 3:
        return pcm_s16le

    peak = max(abs(sample) for sample in prepared)
    if 0 < peak < 16000:
        gain = min(8.0, 16000 / peak)
        prepared = array(
            "h",
            (
                max(-32768, min(32767, round(sample * gain)))
                for sample in prepared
            ),
        )
    if sys.byteorder != "little":
        prepared.byteswap()
    return prepared.tobytes()


class MacOSSpeechTranscriber:
    def __init__(self, app_bundle: Path) -> None:
        self.app_bundle = app_bundle
        self.executable = app_bundle / "Contents/MacOS/BabyTapTranscriber"

    def available(self) -> bool:
        return self.executable.is_file()

    def transcribe_pcm(self, pcm_s16le: bytes, sample_rate: int) -> str:
        return self.transcribe_pcm_result(pcm_s16le, sample_rate).transcript

    def transcribe_pcm_result(
        self, pcm_s16le: bytes, sample_rate: int
    ) -> SpeechTranscription:
        if not self.available():
            raise SpeechTranscriptionError("macOS 语音识别组件尚未构建")
        if not pcm_s16le or sample_rate <= 0:
            raise SpeechTranscriptionError("没有收到可识别的键盘录音")
        prepared_pcm = prepare_pcm_for_speech(pcm_s16le, sample_rate)
        with tempfile.TemporaryDirectory(prefix="babytap-speech-") as directory:
            path = Path(directory) / "capture.wav"
            result_path = Path(directory) / "result.json"
            _write_pcm_wav(path, prepared_pcm, sample_rate)
            try:
                result = subprocess.run(
                    [
                        "/usr/bin/open",
                        "-W",
                        "-n",
                        str(self.app_bundle),
                        "--args",
                        str(path),
                        str(result_path),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=45,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise SpeechTranscriptionError(f"语音识别没有完成：{exc}") from exc
            try:
                payload = json.loads(result_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise SpeechTranscriptionError("macOS 语音识别返回了无效结果") from exc
            transcript = str(payload.get("transcript", "")).strip()
            if result.returncode != 0 or not transcript:
                raise SpeechTranscriptionError(
                    str(payload.get("error") or "没有识别到语音内容")
                )
            confidence_value = payload.get("confidence")
            confidence = (
                float(confidence_value)
                if isinstance(confidence_value, (int, float))
                and 0 <= float(confidence_value) <= 1
                else None
            )
            return SpeechTranscription(transcript, confidence)
