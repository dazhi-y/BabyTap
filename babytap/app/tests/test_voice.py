import unittest

from babytap.voice import VoiceParseError, parse_voice


class VoiceParserTests(unittest.TestCase):
    def test_bottle_accepts_arabic_and_chinese_amounts(self) -> None:
        self.assertEqual(parse_voice("bottle", "喝了 120 毫升")["amount_ml"], 120)
        self.assertEqual(parse_voice("bottle", "一百二十毫升")["amount_ml"], 120)
        self.assertEqual(parse_voice("bottle", "120")["amount_ml"], 120)
        self.assertEqual(parse_voice("bottle", "喂了一百二十")["amount_ml"], 120)

    def test_bottle_rejects_invalid_text_and_out_of_range(self) -> None:
        with self.assertRaises(VoiceParseError):
            parse_voice("bottle", "很多")
        with self.assertRaises(VoiceParseError):
            parse_voice("bottle", "1201 毫升")

    def test_solid_food_keeps_short_description(self) -> None:
        result = parse_voice("solid_food", "宝宝吃了 南瓜泥和米糊")
        self.assertEqual(result["description"], "南瓜泥和米糊")


if __name__ == "__main__":
    unittest.main()
