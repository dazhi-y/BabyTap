import json
import unittest

from babytap.easyinput_protocol import (
    ACTION_UUID_TO_KEY,
    AGENT_STATUS_FLAG_BABYTAP_VOLUME,
    AgentStatus,
    SpeakerCue,
    ConfigAck,
    HostAction,
    action_uuid_for_key,
    build_agent_status_report,
    build_babytap_config,
    crc16_ccitt,
    encode_config_reports,
    parse_app_command,
)


class EasyInputProtocolTests(unittest.TestCase):
    def test_all_eight_action_ids_are_stable_and_distinct(self) -> None:
        values = [action_uuid_for_key(key) for key in range(1, 9)]
        self.assertEqual(len(set(values)), 8)
        self.assertEqual(ACTION_UUID_TO_KEY[values[0]], 1)
        self.assertEqual(ACTION_UUID_TO_KEY[values[-1]], 8)

    def test_parses_host_action_with_or_without_report_id(self) -> None:
        action = action_uuid_for_key(2).encode("ascii")
        payload = bytes([5, 0, 1, 36]) + action + bytes(23)
        for report in (payload, bytes([0x11]) + payload):
            parsed = parse_app_command(report)
            self.assertEqual(parsed, HostAction(action.decode("ascii"), 2))

    def test_parses_config_ack(self) -> None:
        data = bytes([1, 1, 0x23, 0x01, 0xCD, 0xAB, 1])
        payload = bytes([3, 0, 1, len(data)]) + data + bytes(52)
        self.assertEqual(parse_app_command(payload), ConfigAck(1, True, 291, 0xABCD, True))

    def test_agent_status_matches_firmware_layout(self) -> None:
        report = build_agent_status_report(
            AgentStatus.RUNNING,
            sequence=7,
            ttl_ms=5000,
            cue=SpeakerCue.TIMER_STARTED,
            source_hash=9,
        )
        self.assertEqual(report[0:3], bytes([0x12, 1, 1]))
        self.assertEqual(
            report[3],
            AGENT_STATUS_FLAG_BABYTAP_VOLUME | int(SpeakerCue.TIMER_STARTED),
        )
        self.assertEqual(int.from_bytes(report[5:9], "little"), 7)
        self.assertEqual(int.from_bytes(report[9:13], "little"), 5000)
        self.assertEqual(int.from_bytes(report[13:17], "little"), 9)

    def test_config_reports_reassemble_to_exact_json_and_crc(self) -> None:
        config = build_babytap_config(
            wifi_ssid="Test WiFi",
            wifi_password="not-a-real-secret",
            audio_host="192.0.2.10",
        )
        reports = list(encode_config_reports(config))
        self.assertGreater(len(reports), 1)
        self.assertTrue(all(len(report) == 64 for report in reports))
        raw = b"".join(report[12 : 12 + report[9]] for report in reports)
        self.assertEqual(json.loads(raw), config)
        self.assertEqual(int.from_bytes(reports[0][10:12], "little"), crc16_ccitt(raw))

    def test_complete_config_rejects_blank_network_fields(self) -> None:
        with self.assertRaises(ValueError):
            build_babytap_config(wifi_ssid="", wifi_password="x", audio_host="host")


if __name__ == "__main__":
    unittest.main()
