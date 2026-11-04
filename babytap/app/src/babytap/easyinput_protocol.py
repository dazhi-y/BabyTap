from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Dict, Iterable, Mapping, Optional, Union
from uuid import UUID, uuid5


USB_VID = 0x303A
USB_PID = 0x1006
REPORT_ID_CONFIG = 0x10
REPORT_ID_APP_COMMAND = 0x11
REPORT_ID_AGENT_STATUS = 0x12
APP_COMMAND_CONFIG_ACK = 0x03
APP_COMMAND_HOST_ACTION = 0x05
CONFIG_MAX_JSON_BYTES = 2048
CONFIG_CHUNK_BYTES = 52
REPORT_PAYLOAD_BYTES = 63

_BABYTAP_ACTION_NAMESPACE = UUID("d12c2ef0-4636-4c67-9c15-317b4e6f08a8")


def action_uuid_for_key(key: int) -> str:
    if key not in range(1, 9):
        raise ValueError("EasyInput key must be between 1 and 8")
    return str(uuid5(_BABYTAP_ACTION_NAMESPACE, f"babytap-key-{key}"))


ACTION_UUID_TO_KEY: Dict[str, int] = {
    action_uuid_for_key(key): key for key in range(1, 9)
}


class AgentStatus(IntEnum):
    IDLE = 0
    RUNNING = 1
    WAITING_USER = 2
    COMPLETED_UNREAD = 3
    FAILED = 4


class SpeakerCue(IntEnum):
    NONE = 0
    TIMER_STARTED = 1
    SIDE_SWITCHED = 2
    BOTTLE_PROMPT = 3
    SOLID_FOOD_PROMPT = 4
    DIAPER_RECORDED = 5
    SLEEP_STARTED = 6
    RECORD_SAVED = 7
    CANCELLED = 8
    UNDONE = 9
    STATUS_IDLE = 10
    STATUS_BREASTFEEDING = 11
    STATUS_SLEEP = 12
    STATUS_WAITING = 13
    FAILED = 14
    NOTHING_TO_UNDO = 15


AGENT_STATUS_FLAG_BABYTAP_VOLUME = 0x80


@dataclass(frozen=True)
class HostAction:
    uuid: str
    key: Optional[int]


@dataclass(frozen=True)
class ConfigAck:
    phase: int
    ok: bool
    byte_count: int
    crc16: int
    saved: bool


AppCommand = Union[HostAction, ConfigAck]


def _app_payload(report: bytes) -> Optional[bytes]:
    if len(report) >= REPORT_PAYLOAD_BYTES + 1 and report[0] == REPORT_ID_APP_COMMAND:
        return report[1 : REPORT_PAYLOAD_BYTES + 1]
    if len(report) >= REPORT_PAYLOAD_BYTES:
        return report[:REPORT_PAYLOAD_BYTES]
    return None


def parse_app_command(report: bytes) -> Optional[AppCommand]:
    payload = _app_payload(report)
    if payload is None:
        return None

    kind, chunk_index, total_chunks, data_length = payload[:4]
    if chunk_index != 0 or total_chunks != 1 or data_length > 59:
        return None
    data = payload[4 : 4 + data_length]

    if kind == APP_COMMAND_HOST_ACTION and data_length == 36:
        try:
            value = data.decode("ascii")
            canonical = str(UUID(value))
        except (UnicodeDecodeError, ValueError):
            return None
        if canonical != value:
            return None
        return HostAction(uuid=value, key=ACTION_UUID_TO_KEY.get(value))

    if kind == APP_COMMAND_CONFIG_ACK and data_length == 7:
        return ConfigAck(
            phase=data[0],
            ok=data[1] == 1,
            byte_count=int.from_bytes(data[2:4], "little"),
            crc16=int.from_bytes(data[4:6], "little"),
            saved=data[6] == 1,
        )
    return None


def build_agent_status_report(
    state: AgentStatus,
    *,
    sequence: int,
    ttl_ms: int,
    cue: SpeakerCue = SpeakerCue.NONE,
    source_hash: int = 0x42414259,
) -> bytes:
    if not 0 <= sequence <= 0xFFFFFFFF:
        raise ValueError("sequence must fit uint32")
    if not 0 <= ttl_ms <= 12 * 60 * 60 * 1000:
        raise ValueError("ttl_ms exceeds the firmware maximum")
    if state is AgentStatus.IDLE:
        ttl_ms = 0
    payload = bytearray(16)
    payload[0] = 1
    payload[1] = int(state)
    payload[2] = AGENT_STATUS_FLAG_BABYTAP_VOLUME | int(cue)
    struct.pack_into("<III", payload, 4, sequence, ttl_ms, source_hash)
    return bytes([REPORT_ID_AGENT_STATUS]) + bytes(payload)


def crc16_ccitt(data: bytes) -> int:
    crc = 0xFFFF
    for value in data:
        crc ^= value << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def encode_config_reports(config: Mapping[str, object]) -> Iterable[bytes]:
    raw = json.dumps(config, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if not raw or len(raw) > CONFIG_MAX_JSON_BYTES:
        raise ValueError("configuration must be 1..2048 UTF-8 bytes")
    total_chunks = math.ceil(len(raw) / CONFIG_CHUNK_BYTES)
    checksum = crc16_ccitt(raw)
    for index in range(total_chunks):
        chunk = raw[index * CONFIG_CHUNK_BYTES : (index + 1) * CONFIG_CHUNK_BYTES]
        payload = bytearray(REPORT_PAYLOAD_BYTES)
        payload[0:4] = b"S3C\x01"
        payload[4] = index
        payload[5] = total_chunks
        payload[6:8] = len(raw).to_bytes(2, "little")
        payload[8] = len(chunk)
        payload[9:11] = checksum.to_bytes(2, "little")
        payload[11 : 11 + len(chunk)] = chunk
        yield bytes([REPORT_ID_CONFIG]) + bytes(payload)


def build_babytap_config(
    *,
    wifi_ssid: str,
    wifi_password: str,
    audio_host: str,
    audio_port: int = 17333,
    target_platform: str = "macos",
) -> Dict[str, object]:
    """Build a complete replacement config for an explicit setup action.

    The firmware applies config atomically. Callers must never invoke this with
    guessed or blank network fields because that would replace working settings.
    """

    if not wifi_ssid or not wifi_password or not audio_host:
        raise ValueError("Wi-Fi SSID, password and audio host are required")
    if not 1024 <= audio_port <= 65535:
        raise ValueError("audio_port must be between 1024 and 65535")
    if target_platform not in {"macos", "windows"}:
        raise ValueError("target_platform must be macos or windows")

    keys = {
        f"KEY{key}": {"press": f"host_action:{action_uuid_for_key(key)}"}
        for key in range(1, 9)
    }
    return {
        "schema": "ai_keyboard.v1",
        "target_platform": target_platform,
        "wifi_ssid": wifi_ssid,
        "wifi_password": wifi_password,
        "audio_host": audio_host,
        "audio_port": audio_port,
        "microphone_source": "keyboard",
        "audio_source": "wifi_udp",
        "audio_enabled": True,
        "hotkey_mode": "toggle",
        "profiles": [
            {
                "id": "babytap",
                "keys": keys,
                "encoder": {
                    "left": "disabled",
                    "right": "disabled",
                    "press": "disabled",
                },
            }
        ],
    }
