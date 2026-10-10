"""LibVLC options chosen for reliable X11/XWayland wallpaper playback."""

import logging
import os

logger = logging.getLogger("Hidamari")


# The PulseAudio protocol is provided by pipewire-pulse on CachyOS. Keeping
# this stable backend avoids crashes reported by VLC's PipeWire plugin when
# one LibVLC instance is created per monitor.
BASE_VLC_OPTIONS = (
    "--no-disable-screensaver",
    "--aout=pulse",
    "--no-video-title-show",
    # Let VLC discard frames rather than letting late decoding stall the desktop.
    "--drop-late-frames",
    "--skip-frames",
)


def build_vlc_options(hwaccel=None):
    """Build LibVLC options without assuming Vulkan or a specific GPU driver.

    ``HIDAMARI_HWACCEL`` may be set to ``auto`` (default), ``vaapi``,
    ``vdpau`` or ``software``. Auto deliberately leaves LibVLC's automatic
    decoder selection enabled; this lets Mesa VA-API work where available and
    keeps software decoding as a fallback.
    """
    options = list(BASE_VLC_OPTIONS)
    mode = (hwaccel or os.environ.get("HIDAMARI_HWACCEL", "auto")).strip().lower()

    if mode in {"", "auto"}:
        return options
    if mode in {"software", "none", "off"}:
        options.append("--avcodec-hw=none")
    elif mode in {"vaapi", "vdpau"}:
        options.append(f"--avcodec-hw={mode}")
    else:
        logger.warning("Ignoring unsupported HIDAMARI_HWACCEL=%r; using automatic decoding", mode)
    return options
