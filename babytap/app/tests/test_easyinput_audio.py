import unittest

from babytap.easyinput_audio import (
    EasyInputAudioReceiver,
    build_control_packet,
    parse_audio_frame,
    parse_control_ack,
    parse_heartbeat,
)


class EasyInputAudioTests(unittest.TestCase):
    def test_heartbeat(self) -> None:
        packet = b"EIHB" + bytes([1, 3, 0, 0]) + (42).to_bytes(8, "little") + (9).to_bytes(4, "little")
        parsed = parse_heartbeat(packet)
        self.assertTrue(parsed.streaming)
        self.assertTrue(parsed.audio_ready)
        self.assertEqual(parsed.session_id, 42)

    def test_receiver_exposes_fresh_wifi_device_address(self) -> None:
        receiver = EasyInputAudioReceiver(port=17333)
        packet = b"EIHB" + bytes([1, 2, 0, 0]) + (42).to_bytes(8, "little") + (9).to_bytes(4, "little")
        receiver._consume(packet, ("172.20.10.9", 49152))

        snapshot = receiver.snapshot()

        self.assertTrue(snapshot["device_discovered"])
        self.assertEqual(snapshot["device_ip"], "172.20.10.9")
        self.assertEqual(snapshot["device_port"], 49152)

    def test_control_packet(self) -> None:
        packet = build_control_packet(1, 42, 9)
        self.assertEqual(packet[:6], b"EICC\x01\x01")
        self.assertEqual(int.from_bytes(packet[8:16], "little"), 42)

    def test_control_ack(self) -> None:
        packet = b"EICA" + bytes([1, 1, 0, 0]) + (42).to_bytes(8, "little") + (9).to_bytes(4, "little")
        parsed = parse_control_ack(packet)
        self.assertEqual((parsed.action, parsed.status, parsed.session_id), (1, 0, 42))

    def test_audio_frame(self) -> None:
        pcm = bytes(range(16))
        header = bytearray(32)
        header[:8] = b"EIAU\x02\x20\x01\x01"
        header[8:16] = (42).to_bytes(8, "little")
        header[16:20] = (7).to_bytes(4, "little")
        header[20:24] = (16000).to_bytes(4, "little")
        header[24:28] = (1234).to_bytes(4, "little")
        header[28:30] = (8).to_bytes(2, "little")
        header[30:32] = len(pcm).to_bytes(2, "little")
        parsed = parse_audio_frame(bytes(header) + pcm)
        self.assertEqual(parsed.sequence, 7)
        self.assertEqual(parsed.sample_rate, 16000)
        self.assertEqual(parsed.pcm_s16le, pcm)

    def test_rejects_inconsistent_pcm_length(self) -> None:
        packet = bytearray(32)
        packet[:8] = b"EIAU\x02\x20\x01\x01"
        packet[8:16] = (1).to_bytes(8, "little")
        packet[20:24] = (16000).to_bytes(4, "little")
        packet[28:30] = (320).to_bytes(2, "little")
        packet[30:32] = (640).to_bytes(2, "little")
        self.assertIsNone(parse_audio_frame(bytes(packet)))

    def test_receiver_reports_capture_peak_and_rms_without_storing_extra_audio(self) -> None:
        receiver = EasyInputAudioReceiver(port=17333)
        receiver._capture_active = True
        receiver._session_id = 42
        samples = (0, 1000, -2000, 3000)
        pcm = b"".join(sample.to_bytes(2, "little", signed=True) for sample in samples)
        header = bytearray(32)
        header[:8] = b"EIAU\x02\x20\x01\x01"
        header[8:16] = (42).to_bytes(8, "little")
        header[16:20] = (1).to_bytes(4, "little")
        header[20:24] = (16000).to_bytes(4, "little")
        header[28:30] = len(samples).to_bytes(2, "little")
        header[30:32] = len(pcm).to_bytes(2, "little")

        receiver._consume(bytes(header) + pcm, ("172.20.10.9", 49152))
        snapshot = receiver.snapshot()

        self.assertEqual(snapshot["peak_amplitude"], 3000)
        self.assertEqual(snapshot["rms_amplitude"], 1870)
        self.assertEqual(snapshot["pcm_bytes"], len(pcm))


if __name__ == "__main__":
    unittest.main()
