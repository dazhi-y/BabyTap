from pathlib import Path
import tempfile
import unittest

from babytap.easyinput_ble import find_device_identifier_in_log


class EasyInputBleTests(unittest.TestCase):
    def test_uses_latest_official_app_peripheral_identifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "app.log"
            path.write_text(
                "peripheral=11111111-1111-1111-1111-111111111111\n"
                "peripheral=7ebc19c9-630c-da01-b501-ce7a6346e93a\n",
                encoding="utf-8",
            )
            self.assertEqual(
                find_device_identifier_in_log(path),
                "7EBC19C9-630C-DA01-B501-CE7A6346E93A",
            )

    def test_missing_log_is_not_an_error(self) -> None:
        self.assertIsNone(find_device_identifier_in_log(Path("/missing/app.log")))


if __name__ == "__main__":
    unittest.main()
