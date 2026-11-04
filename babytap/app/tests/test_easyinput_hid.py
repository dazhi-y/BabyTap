import unittest

from babytap.easyinput_hid import EasyInputHidDevice
from babytap.easyinput_protocol import (
    AGENT_STATUS_FLAG_BABYTAP_VOLUME,
    AgentStatus,
    SpeakerCue,
    action_uuid_for_key,
)


class FakeHid:
    def __init__(self) -> None:
        self.opened = None
        self.nonblocking = None
        self.reads = []
        self.writes = []

    def open(self, vid, pid) -> None:
        self.opened = (vid, pid)

    def set_nonblocking(self, value) -> None:
        self.nonblocking = value

    def read(self, _length, _timeout):
        return self.reads.pop(0) if self.reads else []

    def send_feature_report(self, report) -> int:
        self.writes.append(bytes(report))
        return len(report)

    def close(self) -> None:
        pass


class EasyInputHidDeviceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = FakeHid()
        self.device = EasyInputHidDevice(self.raw)
        self.device.open()

    def test_reads_maker_host_action(self) -> None:
        action = action_uuid_for_key(4).encode("ascii")
        self.raw.reads.append(bytes([0x11, 5, 0, 1, 36]) + action + bytes(23))
        command = self.device.read_command()
        self.assertEqual(command.key, 4)

    def test_sends_agent_status_as_feature_report(self) -> None:
        self.device.send_agent_status(
            AgentStatus.RUNNING, 5000, SpeakerCue.TIMER_STARTED
        )
        self.assertEqual(self.raw.writes[0][0], 0x12)
        self.assertEqual(
            self.raw.writes[0][3],
            AGENT_STATUS_FLAG_BABYTAP_VOLUME | int(SpeakerCue.TIMER_STARTED),
        )
        self.assertEqual(len(self.raw.writes[0]), 17)


if __name__ == "__main__":
    unittest.main()
