from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from typing import Callable, Dict, Optional, Union

from .easyinput_protocol import (
    USB_PID,
    USB_VID,
    AgentStatus,
    SpeakerCue,
    ConfigAck,
    HostAction,
    build_agent_status_report,
    encode_config_reports,
    parse_app_command,
)


class EasyInputUnavailable(RuntimeError):
    pass


@dataclass
class DeviceSnapshot:
    enabled: bool = False
    connected: bool = False
    last_error: Optional[str] = None
    last_key: Optional[int] = None
    last_config_ack: Optional[Dict[str, object]] = None


class EasyInputHidDevice:
    """Thin hidapi adapter for the Maker firmware's existing reports."""

    def __init__(self, raw_device: Optional[object] = None) -> None:
        self._device = raw_device
        self._sequence = 0

    def open(self) -> None:
        if self._device is None:
            try:
                import hid  # type: ignore
            except ImportError as exc:
                raise EasyInputUnavailable(
                    "hidapi is not installed; install the BabyTap app dependencies"
                ) from exc
            self._device = hid.device()
        try:
            self._device.open(USB_VID, USB_PID)
            self._device.set_nonblocking(False)
        except Exception as exc:
            raise EasyInputUnavailable(f"EasyInput USB device is unavailable: {exc}") from exc

    def close(self) -> None:
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass

    def read_command(
        self, timeout_ms: int = 200
    ) -> Optional[Union[HostAction, ConfigAck]]:
        if self._device is None:
            raise EasyInputUnavailable("EasyInput USB device is not open")
        data = self._device.read(64, timeout_ms)
        return parse_app_command(bytes(data)) if data else None

    def send_agent_status(
        self,
        state: AgentStatus,
        ttl_ms: int,
        cue: SpeakerCue = SpeakerCue.NONE,
    ) -> None:
        if self._device is None:
            raise EasyInputUnavailable("EasyInput USB device is not open")
        self._sequence = (self._sequence + 1) & 0xFFFFFFFF
        report = build_agent_status_report(
            state, sequence=self._sequence, ttl_ms=ttl_ms, cue=cue
        )
        written = self._device.send_feature_report(report)
        if written <= 0:
            raise EasyInputUnavailable("EasyInput rejected the Agent Status report")

    def replace_config(self, config: Dict[str, object]) -> None:
        """Replace the complete device config after an explicit setup action."""

        if self._device is None:
            raise EasyInputUnavailable("EasyInput USB device is not open")
        for report in encode_config_reports(config):
            written = self._device.send_feature_report(report)
            if written <= 0:
                raise EasyInputUnavailable("EasyInput rejected a configuration chunk")


class EasyInputHidListener:
    def __init__(
        self,
        on_key: Callable[[int], None],
        *,
        enabled: bool,
        retry_seconds: float = 1.0,
        device_factory: Callable[[], EasyInputHidDevice] = EasyInputHidDevice,
    ) -> None:
        self._on_key = on_key
        self._retry_seconds = retry_seconds
        self._device_factory = device_factory
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._device: Optional[EasyInputHidDevice] = None
        self._device_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state = DeviceSnapshot(enabled=enabled)

    def start(self) -> None:
        if not self._state.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, name="babytap-easyinput", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        self._disconnect()

    def snapshot(self) -> Dict[str, object]:
        with self._state_lock:
            return asdict(self._state)

    def send_agent_status(
        self,
        state: AgentStatus,
        ttl_ms: int,
        cue: SpeakerCue = SpeakerCue.NONE,
    ) -> bool:
        with self._device_lock:
            if self._device is None:
                return False
            try:
                self._device.send_agent_status(state, ttl_ms, cue)
                return True
            except Exception as exc:
                self._set_state(connected=False, last_error=str(exc))
                return False

    def _set_state(self, **changes: object) -> None:
        with self._state_lock:
            for field, value in changes.items():
                setattr(self._state, field, value)

    def _disconnect(self) -> None:
        with self._device_lock:
            if self._device is not None:
                self._device.close()
                self._device = None
        self._set_state(connected=False)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                device = self._device_factory()
                device.open()
                with self._device_lock:
                    self._device = device
                self._set_state(connected=True, last_error=None)
                self._read_loop(device)
            except Exception as exc:
                self._set_state(connected=False, last_error=str(exc))
            finally:
                self._disconnect()
            self._stop.wait(self._retry_seconds)

    def _read_loop(self, device: EasyInputHidDevice) -> None:
        while not self._stop.is_set():
            command = device.read_command()
            if isinstance(command, HostAction):
                if command.key is None:
                    continue
                self._set_state(last_key=command.key)
                self._on_key(command.key)
            elif isinstance(command, ConfigAck):
                self._set_state(last_config_ack=asdict(command))
