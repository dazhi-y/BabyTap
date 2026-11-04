from __future__ import annotations

import secrets
import socket
import struct
import threading
import time
import math
from dataclasses import asdict
from dataclasses import dataclass
from typing import Dict, Optional, Tuple


HEARTBEAT_FRESH_SECONDS = 6.0


@dataclass(frozen=True)
class AudioHeartbeat:
    streaming: bool
    audio_ready: bool
    session_id: int
    sequence: int


@dataclass(frozen=True)
class AudioControlAck:
    action: int
    status: int
    session_id: int
    sequence: int


@dataclass(frozen=True)
class AudioFrame:
    session_id: int
    sequence: int
    sample_rate: int
    timestamp_ms: int
    frame_samples: int
    pcm_s16le: bytes


def new_session_id() -> int:
    return secrets.randbits(64) or 1


def parse_heartbeat(packet: bytes) -> Optional[AudioHeartbeat]:
    if len(packet) < 20 or packet[:4] != b"EIHB" or packet[4] != 1:
        return None
    flags = packet[5]
    return AudioHeartbeat(
        streaming=bool(flags & 0x01),
        audio_ready=bool(flags & 0x02),
        session_id=int.from_bytes(packet[8:16], "little"),
        sequence=int.from_bytes(packet[16:20], "little"),
    )


def build_control_packet(action: int, session_id: int, sequence: int) -> bytes:
    if action not in {1, 2, 3}:
        raise ValueError("audio action must be start, stop or keepalive")
    if not 0 < session_id <= 0xFFFFFFFFFFFFFFFF:
        raise ValueError("session_id must be a non-zero uint64")
    if not 0 <= sequence <= 0xFFFFFFFF:
        raise ValueError("sequence must fit uint32")
    packet = bytearray(36)
    packet[:4] = b"EICC"
    packet[4] = 1
    packet[5] = action
    struct.pack_into("<QI", packet, 8, session_id, sequence)
    return bytes(packet)


def parse_control_ack(packet: bytes) -> Optional[AudioControlAck]:
    if len(packet) < 20 or packet[:4] != b"EICA" or packet[4] != 1:
        return None
    action = packet[5]
    status = packet[6]
    if action not in {1, 2, 3} or status > 3:
        return None
    return AudioControlAck(
        action=action,
        status=status,
        session_id=int.from_bytes(packet[8:16], "little"),
        sequence=int.from_bytes(packet[16:20], "little"),
    )


def parse_audio_frame(packet: bytes) -> Optional[AudioFrame]:
    if (
        len(packet) < 32
        or packet[:4] != b"EIAU"
        or packet[4] != 2
        or packet[5] != 32
        or packet[6] != 1
        or packet[7] != 1
    ):
        return None
    session_id = int.from_bytes(packet[8:16], "little")
    sequence = int.from_bytes(packet[16:20], "little")
    sample_rate = int.from_bytes(packet[20:24], "little")
    timestamp_ms = int.from_bytes(packet[24:28], "little")
    frame_samples = int.from_bytes(packet[28:30], "little")
    payload_bytes = int.from_bytes(packet[30:32], "little")
    if (
        session_id == 0
        or sample_rate == 0
        or frame_samples == 0
        or payload_bytes != frame_samples * 2
        or len(packet) != 32 + payload_bytes
    ):
        return None
    return AudioFrame(
        session_id=session_id,
        sequence=sequence,
        sample_rate=sample_rate,
        timestamp_ms=timestamp_ms,
        frame_samples=frame_samples,
        pcm_s16le=packet[32:],
    )


class EasyInputAudioReceiver:
    """Receives Maker heartbeats/audio and controls one microphone session."""

    def __init__(self, *, bind_host: str = "0.0.0.0", port: int = 17333) -> None:
        self._bind_host = bind_host
        self._port = port
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._socket: Optional[socket.socket] = None
        self._device_address: Optional[Tuple[str, int]] = None
        self._last_heartbeat_monotonic = 0.0
        self._heartbeat: Optional[AudioHeartbeat] = None
        self._session_id = 0
        self._control_sequence = 0
        self._last_keepalive_monotonic = 0.0
        self._capture_active = False
        self._pcm = bytearray()
        self._sample_rate = 0
        self._frames = 0
        self._sequence_gaps = 0
        self._last_frame_sequence: Optional[int] = None
        self._sample_count = 0
        self._sample_square_sum = 0
        self._peak_amplitude = 0
        self._last_ack: Optional[AudioControlAck] = None
        self._last_error: Optional[str] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp.bind((self._bind_host, self._port))
        udp.settimeout(0.25)
        self._socket = udp
        self._thread = threading.Thread(
            target=self._run, name="babytap-audio", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            heartbeat_age = (
                time.monotonic() - self._last_heartbeat_monotonic
                if self._last_heartbeat_monotonic
                else None
            )
            device_discovered = (
                self._device_address is not None
                and heartbeat_age is not None
                and heartbeat_age <= HEARTBEAT_FRESH_SECONDS
            )
            return {
                "listening": self._thread is not None,
                "port": self._port,
                "device_discovered": device_discovered,
                "device_ip": self._device_address[0] if device_discovered else None,
                "device_port": self._device_address[1] if device_discovered else None,
                "heartbeat_age_seconds": heartbeat_age,
                "audio_ready": self._heartbeat.audio_ready if self._heartbeat else False,
                "heartbeat_streaming": (
                    self._heartbeat.streaming if self._heartbeat else False
                ),
                "heartbeat_session_id": (
                    self._heartbeat.session_id if self._heartbeat else None
                ),
                "heartbeat_sequence": (
                    self._heartbeat.sequence if self._heartbeat else None
                ),
                "capture_active": self._capture_active,
                "session_id": self._session_id or None,
                "sample_rate": self._sample_rate or None,
                "frames": self._frames,
                "pcm_bytes": len(self._pcm),
                "sequence_gaps": self._sequence_gaps,
                "peak_amplitude": self._peak_amplitude,
                "rms_amplitude": (
                    math.isqrt(self._sample_square_sum // self._sample_count)
                    if self._sample_count
                    else 0
                ),
                "last_ack": asdict(self._last_ack) if self._last_ack else None,
                "last_error": self._last_error,
            }

    def begin_capture(self) -> int:
        with self._lock:
            if self._socket is None or self._device_address is None:
                raise RuntimeError("no EasyInput audio heartbeat has been discovered")
            if self._heartbeat is None or not self._heartbeat.audio_ready:
                raise RuntimeError("EasyInput microphone is not ready")
            if self._capture_active:
                raise RuntimeError("EasyInput microphone is already capturing")
            self._session_id = new_session_id()
            self._capture_active = True
            self._pcm.clear()
            self._sample_rate = 0
            self._frames = 0
            self._sequence_gaps = 0
            self._last_frame_sequence = None
            self._sample_count = 0
            self._sample_square_sum = 0
            self._peak_amplitude = 0
            self._last_ack = None
            self._last_error = None
            self._send_control_locked(1)
            self._last_keepalive_monotonic = time.monotonic()
            return self._session_id

    def end_capture(self) -> Dict[str, object]:
        with self._lock:
            if self._capture_active:
                self._send_control_locked(2)
                self._capture_active = False
            return {
                "session_id": self._session_id or None,
                "sample_rate": self._sample_rate or None,
                "frames": self._frames,
                "pcm_bytes": len(self._pcm),
                "sequence_gaps": self._sequence_gaps,
                "peak_amplitude": self._peak_amplitude,
                "rms_amplitude": (
                    math.isqrt(self._sample_square_sum // self._sample_count)
                    if self._sample_count
                    else 0
                ),
            }

    def take_pcm(self) -> bytes:
        with self._lock:
            result = bytes(self._pcm)
            self._pcm.clear()
            return result

    def _send_control_locked(self, action: int) -> None:
        if self._socket is None or self._device_address is None or self._session_id == 0:
            raise RuntimeError("audio control channel is not ready")
        self._control_sequence = (self._control_sequence + 1) & 0xFFFFFFFF
        packet = build_control_packet(action, self._session_id, self._control_sequence)
        self._socket.sendto(packet, self._device_address)

    def _run(self) -> None:
        while not self._stop.is_set():
            udp = self._socket
            if udp is None:
                return
            try:
                packet, address = udp.recvfrom(4096)
            except socket.timeout:
                packet = b""
                address = ("", 0)
            except OSError as exc:
                if not self._stop.is_set():
                    with self._lock:
                        self._last_error = str(exc)
                return
            if packet:
                self._consume(packet, address)
            with self._lock:
                now = time.monotonic()
                if (
                    self._capture_active
                    and now - self._last_keepalive_monotonic >= 5.0
                ):
                    try:
                        self._send_control_locked(3)
                        self._last_keepalive_monotonic = now
                    except OSError as exc:
                        self._last_error = str(exc)

    def _consume(self, packet: bytes, address: Tuple[str, int]) -> None:
        heartbeat = parse_heartbeat(packet)
        if heartbeat is not None:
            with self._lock:
                self._device_address = address
                self._last_heartbeat_monotonic = time.monotonic()
                self._heartbeat = heartbeat
            return
        ack = parse_control_ack(packet)
        if ack is not None:
            with self._lock:
                self._last_ack = ack
                if ack.status != 0:
                    self._last_error = f"audio control rejected with status {ack.status}"
                    if ack.action == 3 and ack.session_id == self._session_id:
                        self._capture_active = False
            return
        frame = parse_audio_frame(packet)
        if frame is None:
            return
        with self._lock:
            if not self._capture_active or frame.session_id != self._session_id:
                return
            if (
                self._last_frame_sequence is not None
                and frame.sequence != (self._last_frame_sequence + 1) & 0xFFFFFFFF
            ):
                self._sequence_gaps += 1
            self._last_frame_sequence = frame.sequence
            if self._sample_rate not in {0, frame.sample_rate}:
                self._last_error = "audio sample rate changed during capture"
                return
            self._sample_rate = frame.sample_rate
            self._pcm.extend(frame.pcm_s16le)
            for (sample,) in struct.iter_unpack("<h", frame.pcm_s16le):
                amplitude = abs(sample)
                self._sample_count += 1
                self._sample_square_sum += sample * sample
                if amplitude > self._peak_amplitude:
                    self._peak_amplitude = amplitude
            self._frames += 1
