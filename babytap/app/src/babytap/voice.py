from __future__ import annotations

from dataclasses import asdict, dataclass
import re
from threading import RLock
from typing import Dict, Optional


class VoiceParseError(ValueError):
    pass


_CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _chinese_number(value: str) -> int:
    if "百" in value:
        hundreds, rest = value.split("百", 1)
        total = _CHINESE_DIGITS.get(hundreds or "一", 1) * 100
        return total + (_chinese_number(rest) if rest else 0)
    if "十" in value:
        tens, ones = value.split("十", 1)
        return _CHINESE_DIGITS.get(tens or "一", 1) * 10 + _CHINESE_DIGITS.get(
            ones, 0
        )
    if not value:
        return 0
    digits = "".join(str(_CHINESE_DIGITS[char]) for char in value)
    return int(digits)


def parse_voice(context: str, transcript: str) -> Dict[str, object]:
    text = " ".join(transcript.strip().split())
    if not text:
        raise VoiceParseError("没有识别到内容，请重试")

    if context == "bottle":
        arabic = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:毫升|ml|mL)", text)
        chinese = re.search(r"([零〇一二两三四五六七八九十百]+)\s*毫升", text)
        bare_arabic = re.fullmatch(r"(?:宝宝)?(?:喝了|喂了|奶瓶)?\s*(\d+(?:\.\d+)?)", text)
        bare_chinese = re.fullmatch(
            r"(?:宝宝)?(?:喝了|喂了|奶瓶)?\s*([零〇一二两三四五六七八九十百]+)",
            text,
        )
        if arabic:
            amount = float(arabic.group(1))
        elif chinese:
            amount = float(_chinese_number(chinese.group(1)))
        elif bare_arabic:
            amount = float(bare_arabic.group(1))
        elif bare_chinese:
            amount = float(_chinese_number(bare_chinese.group(1)))
        else:
            raise VoiceParseError("请输入奶量，例如“120”或“120 毫升”")
        if not 1 <= amount <= 1000:
            raise VoiceParseError("奶量必须在 1–1000 ml 之间")
        return {
            "amount_ml": int(amount) if amount.is_integer() else amount,
            "transcript": text,
        }

    if context == "solid_food":
        description = re.sub(r"^(?:辅食|宝宝吃了|吃了)\s*[:：]?\s*", "", text)
        if not description:
            raise VoiceParseError("请说出辅食内容")
        if len(description) > 120:
            raise VoiceParseError("辅食内容不能超过 120 个字符")
        return {"description": description, "transcript": text}

    raise VoiceParseError(f"不支持的语音场景：{context}")


@dataclass(frozen=True)
class VoiceDraft:
    context: str
    transcript: str
    data: Dict[str, object]

    def as_dict(self) -> Dict[str, object]:
        return asdict(self)


class VoiceDraftStore:
    def __init__(self) -> None:
        self._lock = RLock()
        self._draft: Optional[VoiceDraft] = None

    def submit(self, context: str, transcript: str) -> VoiceDraft:
        draft = VoiceDraft(context, transcript.strip(), parse_voice(context, transcript))
        with self._lock:
            self._draft = draft
        return draft

    def get(self) -> Optional[VoiceDraft]:
        with self._lock:
            return self._draft

    def clear(self) -> None:
        with self._lock:
            self._draft = None
