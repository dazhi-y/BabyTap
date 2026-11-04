from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wave

from babytap.macos_speech import MacOSSpeechTranscriber, prepare_pcm_for_speech


class MacOSSpeechTranscriberTests(unittest.TestCase):
    def test_prepares_low_volume_speech_without_long_quiet_padding(self) -> None:
        sample_rate = 16000
        quiet = [100] * (sample_rate * 2)
        speech = [2000 if index % 8 < 4 else -2000 for index in range(sample_rate)]
        pcm = b"".join(sample.to_bytes(2, "little", signed=True) for sample in quiet + speech + quiet)

        prepared = prepare_pcm_for_speech(pcm, sample_rate)

        self.assertLess(len(prepared), len(pcm))
        self.assertGreater(len(prepared), sample_rate * 2)
        samples = [
            int.from_bytes(prepared[index : index + 2], "little", signed=True)
            for index in range(0, len(prepared), 2)
        ]
        self.assertGreaterEqual(max(abs(sample) for sample in samples), 15000)

    def test_reads_result_before_temporary_capture_directory_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app_bundle = Path(directory) / "BabyTapTranscriber.app"
            executable = app_bundle / "Contents/MacOS/BabyTapTranscriber"
            executable.parent.mkdir(parents=True)
            executable.touch()
            transcriber = MacOSSpeechTranscriber(app_bundle)

            def run_transcriber(arguments, **_kwargs):
                with wave.open(arguments[-2], "rb") as capture:
                    self.assertGreater(capture.getnframes(), 0)
                result_path = Path(arguments[-1])
                result_path.write_text(
                    '{"transcript":"奶瓶一百二十毫升","confidence":0.91}',
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(arguments, 0, "", "")

            with patch(
                "babytap.macos_speech.subprocess.run", side_effect=run_transcriber
            ):
                transcript = transcriber.transcribe_pcm(b"\x00\x00" * 160, 16000)

        self.assertEqual(transcript, "奶瓶一百二十毫升")

    def test_returns_confidence_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            app_bundle = Path(directory) / "BabyTapTranscriber.app"
            executable = app_bundle / "Contents/MacOS/BabyTapTranscriber"
            executable.parent.mkdir(parents=True)
            executable.touch()
            transcriber = MacOSSpeechTranscriber(app_bundle)

            def run_transcriber(arguments, **_kwargs):
                Path(arguments[-1]).write_text(
                    '{"transcript":"米粉加蛋黄","confidence":0.82}',
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(arguments, 0, "", "")

            with patch(
                "babytap.macos_speech.subprocess.run", side_effect=run_transcriber
            ):
                result = transcriber.transcribe_pcm_result(
                    b"\x00\x00" * 160, 16000
                )

        self.assertEqual(result.transcript, "米粉加蛋黄")
        self.assertEqual(result.confidence, 0.82)


if __name__ == "__main__":
    unittest.main()
