import base64
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave

import httpx

from babytap.dashscope_speech import (
    DASHSCOPE_ASR_MODEL,
    DashScopeSpeechTranscriber,
)
from babytap.macos_speech import SpeechTranscriptionError


class DashScopeSpeechTranscriberTests(unittest.TestCase):
    def test_sends_lesson_seven_asr_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "dashscope.env"
            key_path.write_text("DASHSCOPE_API_KEY=test-secret\n", encoding="utf-8")
            key_path.chmod(0o600)
            transcriber = DashScopeSpeechTranscriber(key_path)

            def post(_url, *, headers, json, timeout):
                self.assertEqual(headers["Authorization"], "Bearer test-secret")
                self.assertEqual(timeout, 45.0)
                self.assertEqual(json["model"], DASHSCOPE_ASR_MODEL)
                self.assertEqual(json["asr_options"], {"language": "zh", "enable_itn": True})
                encoded = json["messages"][0]["content"][0]["input_audio"]["data"]
                wav_bytes = base64.b64decode(encoded.removeprefix("data:audio/wav;base64,"))
                wav_path = Path(directory) / "request.wav"
                wav_path.write_bytes(wav_bytes)
                with wave.open(str(wav_path), "rb") as capture:
                    self.assertEqual(capture.getnchannels(), 1)
                    self.assertEqual(capture.getframerate(), 16000)
                    self.assertEqual(capture.getsampwidth(), 2)
                return httpx.Response(
                    200,
                    json={"choices": [{"message": {"content": "120 毫升"}}]},
                )

            with patch("babytap.dashscope_speech.httpx.post", side_effect=post):
                result = transcriber.transcribe_pcm_result(b"\x01\x00" * 160, 16000)

        self.assertEqual(result.transcript, "120 毫升")
        self.assertIsNone(result.confidence)

    def test_requires_private_key_file_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            key_path = Path(directory) / "dashscope.env"
            key_path.write_text("DASHSCOPE_API_KEY=test-secret\n", encoding="utf-8")
            key_path.chmod(0o644)

            with self.assertRaisesRegex(SpeechTranscriptionError, "权限不安全"):
                DashScopeSpeechTranscriber(key_path).transcribe_pcm_result(
                    b"\x00\x00" * 160, 16000
                )


if __name__ == "__main__":
    unittest.main()
