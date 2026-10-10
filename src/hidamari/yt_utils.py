"""Utilities for choosing stream formats that suit the current display/GPU."""

import math


def get_formats(raw_url):
    # Keep yt-dlp optional for code which only needs the format selectors (and
    # allow system-packaged yt-dlp to be imported only when streaming is used).
    import yt_dlp

    with yt_dlp.YoutubeDL({"noplaylist": True}) as ydl:
        formats = ydl.extract_info(raw_url, download=False)["formats"]
    return formats


def filter_audio(formats):
    return filter(
        lambda item: item.get("acodec") not in (None, "none") and item.get("vcodec") == "none",
        formats,
    )


def filter_video(formats):
    return filter(
        lambda item: item.get("acodec") == "none" and item.get("vcodec") not in (None, "none"),
        formats,
    )


def filter_audio_video(formats):
    return filter(
        lambda item: (
            item.get("acodec") not in (None, "none") and item.get("vcodec") not in (None, "none")
        ),
        formats,
    )


def _number(value, default=0):
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _quality_score(item):
    """Prefer a useful bitrate, while treating absent yt-dlp fields as zero."""
    return (
        _number(item.get("quality"), -1),
        _number(item.get("tbr"), _number(item.get("vbr"))),
        _number(item.get("fps")),
        _number(item.get("width")),
    )


def _usable_video_formats(formats):
    usable = []
    for item in formats:
        if not item.get("url"):
            continue
        width = int(_number(item.get("width")))
        height = int(_number(item.get("height")))
        if width > 0 and height > 0:
            usable.append((item, width, height))
    return usable


def _get_best_video_format(formats):
    candidates = _usable_video_formats(formats)
    if not candidates:
        raise ValueError("No playable video formats were found for this stream")
    item, width, height = max(candidates, key=lambda candidate: _quality_score(candidate[0]))
    return item["url"], width, height


def get_best(formats):
    """Return the best combined audio/video format, if the source has one."""
    return _get_best_video_format(filter_audio_video(formats))


def get_best_audio(formats):
    """Return the best audio-only URL, or None when the stream has no audio."""
    candidates = list(filter_audio(formats))
    if not candidates:
        combined = list(filter_audio_video(formats))
        if not combined:
            return None
        best = max(combined, key=_quality_score)
    else:
        best = max(candidates, key=_quality_score)
    return best.get("url")


def get_best_video(formats):
    """Return the highest-quality video, allowing combined formats as fallback."""
    candidates = list(filter_video(formats))
    if not candidates:
        candidates = list(filter_audio_video(formats))
    return _get_best_video_format(candidates)


def get_optimal_video(formats, height):
    """Choose a stream appropriate for the display and legacy decode hardware.

    A10-era integrated GPUs can often decode H.264/AVC through VA-API but
    generally have no hardware decoder for newer codecs such as AV1. Prefer
    AVC when the source offers it, pick a resolution at or below the target
    (never the next larger size just because it is numerically closer), and
    prefer 30 fps when both 30 and 60 fps variants are available.
    """
    try:
        target_height = max(1, int(height))
    except (TypeError, ValueError):
        target_height = 720

    candidates = list(filter_video(formats))
    if not candidates:
        candidates = list(filter_audio_video(formats))
    usable = _usable_video_formats(candidates)
    if not usable:
        raise ValueError("No playable video formats were found for this stream")

    # The Radeon HD 8650G generation can accelerate AVC/H.264 with a working
    # VA-API driver, while VP9 and AV1 are usually software-decoded on this GPU.
    h264 = [
        candidate
        for candidate in usable
        if str(candidate[0].get("vcodec", "")).lower().startswith(("avc1", "h264"))
    ]
    if h264:
        usable = h264

    at_or_below_target = [candidate for candidate in usable if candidate[2] <= target_height]
    if at_or_below_target:
        selected_height = max(candidate[2] for candidate in at_or_below_target)
        pool = [candidate for candidate in at_or_below_target if candidate[2] == selected_height]
    else:
        # If every format is larger than the display, use the smallest one
        # instead of upscaling decode work further.
        selected_height = min(candidate[2] for candidate in usable)
        pool = [candidate for candidate in usable if candidate[2] == selected_height]

    at_or_below_30fps = [
        candidate for candidate in pool if _number(candidate[0].get("fps"), 30) <= 30
    ]
    if at_or_below_30fps:
        pool = at_or_below_30fps

    item, width, height = max(pool, key=lambda candidate: _quality_score(candidate[0]))
    return item["url"], width, height


if __name__ == "__main__":
    import vlc

    test_url = "https://www.youtube.com/watch?v=hdf9-E0Rt8Q"
    formats = get_formats(test_url)
    instance = vlc.Instance()
    player = instance.media_player_new()
    video_url, video_width, video_height = get_optimal_video(formats, 1080)
    media = instance.media_new(video_url)
    player.set_media(media)
    audio_url = get_best_audio(formats)
    if audio_url:
        player.add_slave(vlc.MediaSlaveType(1), audio_url, True)
    player.play()

    while True:
        pass
