#!/usr/bin/env python3
"""Regenerate BabyTap's fixed Mandarin EIAD prompts on macOS."""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import struct
import subprocess
import tempfile
import wave


SAMPLE_RATE = 48_000
FRAME_SAMPLES = 480
STEP_TABLE = (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
    34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130,
    143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
    494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411,
    1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660,
    4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493,
    10442, 11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385,
    24623, 27086, 29794, 32767,
)
INDEX_DELTA = (-1, -1, -1, -1, 2, 4, 6, 8,
               -1, -1, -1, -1, 2, 4, 6, 8)

CUES = (
    ("01_timer_started", "计时已开始"),
    ("02_side_switched", "已切换另一侧"),
    ("03_bottle_prompt", "请说奶瓶奶量"),
    ("04_solid_food_prompt", "请说辅食内容"),
    ("05_diaper_recorded", "换尿布已记录"),
    ("06_sleep_started", "睡眠计时已开始"),
    ("07_record_saved", "记录成功"),
    ("08_cancelled", "已取消"),
    ("09_undone", "已撤销"),
    ("10_status_idle", "当前没有进行中的记录"),
    ("11_status_breastfeeding", "正在母乳计时"),
    ("12_status_sleep", "正在睡眠计时"),
    ("13_status_waiting", "正在等待语音输入"),
    ("14_failed", "操作失败"),
    ("15_nothing_to_undo", "没有可以撤销的记录"),
)


def nearest_step_index(delta: int) -> int:
    return min(range(len(STEP_TABLE)), key=lambda index: abs(STEP_TABLE[index] - delta))


def encode_nibble(sample: int, predictor: int, step_index: int) -> tuple[int, int, int]:
    step = STEP_TABLE[step_index]
    difference = sample - predictor
    code = 0
    if difference < 0:
        code = 8
        difference = -difference
    reconstructed = step >> 3
    if difference >= step:
        code |= 4
        difference -= step
        reconstructed += step
    if difference >= step >> 1:
        code |= 2
        difference -= step >> 1
        reconstructed += step >> 1
    if difference >= step >> 2:
        code |= 1
        reconstructed += step >> 2
    predictor += -reconstructed if code & 8 else reconstructed
    predictor = max(-32768, min(32767, predictor))
    step_index = max(0, min(88, step_index + INDEX_DELTA[code]))
    return code, predictor, step_index


def encode_eiad(samples: list[int]) -> bytes:
    if not samples:
        raise ValueError("audio must contain samples")
    frame_count = math.ceil(len(samples) / FRAME_SAMPLES)
    encoded = bytearray(
        struct.pack(
            "<4sBBIHHIH",
            b"EIAD",
            1,
            1,
            SAMPLE_RATE,
            FRAME_SAMPLES,
            frame_count,
            len(samples),
            20,
        )
    )
    carried_index = 0
    for offset in range(0, len(samples), FRAME_SAMPLES):
        frame = samples[offset : offset + FRAME_SAMPLES]
        predictor = frame[0]
        lookahead = frame[1 : min(len(frame), 49)]
        if lookahead:
            characteristic_delta = max(
                abs(sample - frame[index])
                for index, sample in enumerate(lookahead)
            )
            carried_index = max(carried_index, nearest_step_index(characteristic_delta))
        frame_index = carried_index
        encoded.extend(struct.pack("<HhBB", len(frame), predictor, frame_index, 0))
        nibbles: list[int] = []
        for sample in frame[1:]:
            code, predictor, carried_index = encode_nibble(
                sample, predictor, carried_index
            )
            nibbles.append(code)
        for index in range(0, len(nibbles), 2):
            low = nibbles[index]
            high = nibbles[index + 1] if index + 1 < len(nibbles) else 0
            encoded.append(low | (high << 4))
    return bytes(encoded)


def load_pcm(path: Path) -> list[int]:
    with wave.open(str(path), "rb") as audio:
        if (
            audio.getnchannels() != 1
            or audio.getsampwidth() != 2
            or audio.getframerate() != SAMPLE_RATE
        ):
            raise ValueError("expected 48 kHz mono PCM16 WAV")
        raw = audio.readframes(audio.getnframes())
    samples = list(struct.unpack(f"<{len(raw) // 2}h", raw))
    peak = max(abs(sample) for sample in samples) or 1
    gain = min(1.0, 26_000 / peak)
    return [max(-32768, min(32767, round(sample * gain))) for sample in samples]


def generate(output: Path, voice: str, rate: int) -> None:
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="babytap-cues-") as temporary:
        temporary_path = Path(temporary)
        for name, phrase in CUES:
            aiff = temporary_path / f"{name}.aiff"
            wav = temporary_path / f"{name}.wav"
            subprocess.run(
                ["say", "-v", voice, "-r", str(rate), "-o", str(aiff), phrase],
                check=True,
            )
            subprocess.run(
                [
                    "afconvert",
                    "-f",
                    "WAVE",
                    "-d",
                    f"LEI16@{SAMPLE_RATE}",
                    "-c",
                    "1",
                    str(aiff),
                    str(wav),
                ],
                check=True,
            )
            destination = output / f"{name}.eiad"
            destination.write_bytes(encode_eiad(load_pcm(wav)))
            print(f"{destination.name}\t{destination.stat().st_size}\t{phrase}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--voice", default="Tingting")
    parser.add_argument("--rate", type=int, default=210)
    arguments = parser.parse_args()
    generate(arguments.output, arguments.voice, arguments.rate)


if __name__ == "__main__":
    main()
