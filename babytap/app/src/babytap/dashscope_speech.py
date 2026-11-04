from __future__ import annotations

import base64
from io import BytesIO
import os
from pathlib import Path
import stat
import wave

import httpx

from .macos_speech import SpeechTranscription, SpeechTranscriptionError


DASHSCOPE_ASR_MODEL = "qwen3-asr-flash"
DASHSCOPE_ASR_ENDPOINT = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
)
MAX_AUDIO_SECONDS = 90


class DashScopeSpeechTranscriber:
    """Transcribe PCM with the Beijing DashScope ASR path used by lesson 7."""

    def __init__(self, key_path: Path, *, endpoint: str = DASHSCOPE_ASR_ENDPOINT) -> None:
        self.key_path = key_path.expanduser()
        self.endpoint = endpoint

    def configured(self) -> bool:
        try:
            self._load_api_key()
        except SpeechTranscriptionError:
            return False
        return True

    def status(self) -> dict:
        return {
            "provider": "dashscope",
            "model": DASHSCOPE_ASR_MODEL,
            "region": "cn-beijing",
            "configured": self.configured(),
        }

    def transcribe_pcm_result(
        self, pcm_s16le: bytes, sample_rate: int
    ) -> SpeechTranscription:
        if not pcm_s16le or len(pcm_s16le) % 2 or not 8000 <= sample_rate <= 96000:
            raise SpeechTranscriptionError("没有收到有效的语音录音")
        if len(pcm_s16le) > sample_rate * 2 * MAX_AUDIO_SECONDS:
            raise SpeechTranscriptionError("语音录音超过 90 秒")

        api_key = self._load_api_key()
        wav = self._wav_bytes(pcm_s16le, sample_rate)
        audio_data = base64.b64encode(wav).decode("ascii")
        payload = {
            "model": DASHSCOPE_ASR_MODEL,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": f"data:audio/wav;base64,{audio_data}"
                            },
                        }
                    ],
                }
            ],
            "stream": False,
            "asr_options": {"language": "zh", "enable_itn": True},
        }
        try:
            response = httpx.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=45.0,
            )
        except httpx.HTTPError as exc:
            raise SpeechTranscriptionError("DashScope 语音识别服务暂时不可用") from exc
        finally:
            api_key = ""

        if response.status_code in {401, 403}:
            raise SpeechTranscriptionError("DashScope API Key 无效或无权限")
        if response.status_code == 429:
            raise SpeechTranscriptionError("DashScope 语音识别请求过于频繁")
        if response.status_code >= 400:
            raise SpeechTranscriptionError(
                f"DashScope 语音识别失败（HTTP {response.status_code}）"
            )
        try:
            body = response.json()
            transcript = str(body["choices"][0]["message"]["content"]).strip()
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise SpeechTranscriptionError("DashScope 返回了无效的识别结果") from exc
        if not transcript:
            raise SpeechTranscriptionError("没有识别到语音内容")
        return SpeechTranscription(transcript=transcript, confidence=None)

    def _load_api_key(self) -> str:
        env_key = os.getenv("BABYTAP_DASHSCOPE_API_KEY", "").strip()
        if env_key:
            return env_key
        try:
            info = self.key_path.stat()
        except FileNotFoundError as exc:
            raise SpeechTranscriptionError(
                "DashScope 尚未配置，请先导入北京区 API Key"
            ) from exc
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise SpeechTranscriptionError("DashScope 配置文件权限不安全，应为 600")
        try:
            lines = self.key_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise SpeechTranscriptionError("无法读取 DashScope 配置") from exc
        values = [
            line.removeprefix("DASHSCOPE_API_KEY=").strip()
            for line in lines
            if line.startswith("DASHSCOPE_API_KEY=")
        ]
        if len(values) != 1 or not values[0]:
            raise SpeechTranscriptionError("DashScope 配置中缺少 API Key")
        return values[0]

    @staticmethod
    def _wav_bytes(pcm_s16le: bytes, sample_rate: int) -> bytes:
        output = BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm_s16le)
        return output.getvalue()
