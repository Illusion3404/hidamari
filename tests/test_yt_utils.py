import unittest

from hidamari.yt_utils import get_best_audio, get_optimal_video


def video_format(codec, height, fps=30, bitrate=1000):
    return {
        "url": f"https://example.invalid/{codec}-{height}-{fps}",
        "vcodec": codec,
        "acodec": "none",
        "width": int(height * 16 / 9),
        "height": height,
        "fps": fps,
        "tbr": bitrate,
    }


class OptimalVideoTests(unittest.TestCase):
    def test_does_not_choose_resolution_above_target(self):
        formats = [video_format("avc1.64001f", 720), video_format("avc1.640028", 1080)]
        url, width, height = get_optimal_video(formats, 900)
        self.assertEqual(height, 720)
        self.assertEqual(width, int(720 * 16 / 9))
        self.assertIn("720", url)

    def test_prefers_h264_for_legacy_hardware(self):
        formats = [video_format("vp9", 1080), video_format("avc1.640028", 720)]
        _, _, height = get_optimal_video(formats, 1080)
        self.assertEqual(height, 720)

    def test_prefers_30_fps_when_available(self):
        formats = [
            video_format("avc1.64001f", 720, fps=30, bitrate=1000),
            video_format("avc1.64001f", 720, fps=60, bitrate=3000),
        ]
        url, _, _ = get_optimal_video(formats, 720)
        self.assertIn("30", url)

    def test_uses_smallest_format_if_all_exceed_target(self):
        formats = [video_format("avc1.640028", 1080), video_format("avc1.640032", 1440)]
        _, _, height = get_optimal_video(formats, 720)
        self.assertEqual(height, 1080)

    def test_raises_when_no_video_format_has_dimensions(self):
        with self.assertRaises(ValueError):
            get_optimal_video([{"url": "x", "vcodec": "avc1", "acodec": "none"}], 720)

    def test_no_audio_is_a_valid_stream_state(self):
        self.assertIsNone(get_best_audio([video_format("avc1.64001f", 720)]))


if __name__ == "__main__":
    unittest.main()
