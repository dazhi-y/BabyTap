from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from pathlib import Path
import queue
import re
import threading
from typing import Dict, Optional, Tuple

from .easyinput_protocol import AgentStatus, SpeakerCue, build_agent_status_report


CONFIG_SERVICE_UUID = "7d2f4d10-6f6b-4a2d-8b01-6d4653320001"
AGENT_STATUS_UUID = "7d2f4d10-6f6b-4a2d-8b01-6d4653320004"
_PERIPHERAL_PATTERN = re.compile(
    r"peripheral=([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})",
    re.IGNORECASE,
)


@dataclass
class BleFeedbackSnapshot:
    enabled: bool = False
    connected: bool = False
    device_identifier: Optional[str] = None
    last_state: Optional[str] = None
    last_error: Optional[str] = None


def find_device_identifier_in_log(path: Path) -> Optional[str]:
    """Use the official app's last CoreBluetooth identifier as a one-time hint."""

    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    matches = _PERIPHERAL_PATTERN.findall(text)
    return matches[-1].upper() if matches else None


class EasyInputBleFeedback:
    """Sends BabyTap state colours over the firmware's existing BLE GATT API."""

    def __init__(
        self,
        *,
        enabled: bool,
        device_identifier: Optional[str] = None,
        official_log: Optional[Path] = None,
    ) -> None:
        self._explicit_identifier = device_identifier
        self._official_log = official_log or (
            Path.home()
            / "Library/Application Support/EasyInput/logs/app.log"
        )
        self._commands: "queue.Queue[Optional[Tuple[AgentStatus, int, SpeakerCue]]]" = queue.Queue(
            maxsize=1
        )
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._state_lock = threading.Lock()
        self._state = BleFeedbackSnapshot(enabled=enabled)

    def start(self) -> None:
        if not self._state.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="babytap-easyinput-ble", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._replace_pending(None)
        if self._thread is not None:
            self._thread.join(timeout=4)
            self._thread = None

    def snapshot(self) -> Dict[str, object]:
        with self._state_lock:
            return asdict(self._state)

    def send_agent_status(
        self,
        state: AgentStatus,
        ttl_ms: int,
        cue: SpeakerCue = SpeakerCue.NONE,
    ) -> bool:
        if not self._state.enabled:
            return False
        self._replace_pending((state, ttl_ms, cue))
        return True

    def _replace_pending(
        self, command: Optional[Tuple[AgentStatus, int, SpeakerCue]]
    ) -> None:
        try:
            self._commands.put_nowait(command)
            return
        except queue.Full:
            pass
        try:
            self._commands.get_nowait()
        except queue.Empty:
            pass
        try:
            self._commands.put_nowait(command)
        except queue.Full:
            pass

    def _set_state(self, **changes: object) -> None:
        with self._state_lock:
            for field, value in changes.items():
                setattr(self._state, field, value)

    def _run(self) -> None:
        try:
            asyncio.run(self._async_run())
        except Exception as exc:
            self._set_state(connected=False, last_error=str(exc))

    async def _resolve_device(self):
        preferred_identifier = self._explicit_identifier or find_device_identifier_in_log(
            self._official_log
        )
        from bleak import BleakScanner  # type: ignore
        from bleak.backends.device import BLEDevice  # type: ignore
        from CoreBluetooth import CBUUID  # type: ignore

        # A paired HID keyboard often stops advertising. CoreBluetooth can
        # still retrieve the connected peripheral by its custom service.
        scanner = BleakScanner(service_uuids=[CONFIG_SERVICE_UUID])
        await scanner.start()
        await asyncio.sleep(0.25)
        backend = scanner._backend
        manager = backend._manager
        peripherals = manager.central_manager.retrieveConnectedPeripheralsWithServices_(
            [CBUUID.UUIDWithString_(CONFIG_SERVICE_UUID)]
        )
        await scanner.stop()
        for peripheral in peripherals:
            identifier = str(peripheral.identifier().UUIDString())
            if preferred_identifier and identifier.upper() != preferred_identifier.upper():
                continue
            return (
                BLEDevice(
                    identifier,
                    peripheral.name(),
                    (peripheral, manager.central_manager.delegate()),
                    -60,
                ),
                scanner,
            )

        device = await BleakScanner.find_device_by_filter(
            lambda candidate, advertisement: (
                (candidate.name or advertisement.local_name or "")
                == "EasyInput AI"
                or CONFIG_SERVICE_UUID in advertisement.service_uuids
            ),
            timeout=6.0,
        )
        return (device, scanner) if device is not None else (None, scanner)

    async def _next_command(self) -> Optional[Tuple[AgentStatus, int, SpeakerCue]]:
        while not self._stop.is_set():
            try:
                return await asyncio.to_thread(self._commands.get, True, 0.5)
            except queue.Empty:
                continue
        return None

    async def _async_run(self) -> None:
        from bleak import BleakClient  # type: ignore

        client = None
        retrieval_scanner = None
        sequence = 0
        try:
            while not self._stop.is_set():
                command = await self._next_command()
                if command is None:
                    continue
                state, ttl_ms, cue = command
                try:
                    device, retrieval_scanner = await self._resolve_device()
                    if device is None:
                        raise RuntimeError("未找到已连接的 EasyInput 蓝牙设备")
                    if client is None or not client.is_connected:
                        client = BleakClient(device, timeout=12.0)
                        await client.connect()
                    sequence = (sequence + 1) & 0xFFFFFFFF
                    payload = build_agent_status_report(
                        state, sequence=sequence, ttl_ms=ttl_ms, cue=cue
                    )[1:]
                    await client.write_gatt_char(
                        AGENT_STATUS_UUID, payload, response=False
                    )
                    self._set_state(
                        connected=True,
                        device_identifier=device.address,
                        last_state=state.name.lower(),
                        last_error=None,
                    )
                except Exception as exc:
                    self._set_state(connected=False, last_error=str(exc))
                    if client is not None:
                        try:
                            await client.disconnect()
                        except Exception:
                            pass
                        client = None
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass
