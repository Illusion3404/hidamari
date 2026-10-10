import os
import unittest
from unittest.mock import patch

from hidamari.player.video_options import build_vlc_options


class VLCOptionTests(unittest.TestCase):
    def test_defaults_to_automatic_decoding(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HIDAMARI_HWACCEL", None)
            options = build_vlc_options()
        self.assertIn("--drop-late-frames", options)
        self.assertIn("--skip-frames", options)
        self.assertFalse(any(option.startswith("--avcodec-hw=") for option in options))

    def test_can_force_legacy_amd_vaapi(self):
        self.assertIn("--avcodec-hw=vaapi", build_vlc_options("vaapi"))

    def test_can_disable_hardware_decoding_for_debugging(self):
        self.assertIn("--avcodec-hw=none", build_vlc_options("software"))

    def test_invalid_override_does_not_prevent_startup(self):
        options = build_vlc_options("not-a-decoder")
        self.assertFalse(any(option.startswith("--avcodec-hw=") for option in options))


if __name__ == "__main__":
    unittest.main()
