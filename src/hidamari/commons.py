import os
import subprocess
from pathlib import Path

LOGGER_NAME = "Hidamari"

PROJECT = "io.github.jeffshee.Hidamari"
DBUS_NAME_SERVER = f"{PROJECT}.server"
DBUS_NAME_PLAYER = f"{PROJECT}.player"

# gettext text domain (matches po/meson.build and the installed hidamari.mo)
TRANSLATION_DOMAIN = "hidamari"

HOME = os.environ.get("HOME") or str(Path.home())
try:
    result = subprocess.run(
        ["xdg-user-dir", "VIDEOS"],
        check=True,
        capture_output=True,
        encoding="UTF-8",
        timeout=3,
    )
    xdg_video_dir = result.stdout.strip()
    if not xdg_video_dir:
        raise ValueError("xdg-user-dir returned an empty path")
    VIDEO_WALLPAPER_DIR = os.path.join(xdg_video_dir, "Hidamari")
except (OSError, subprocess.SubprocessError, ValueError):
    # xdg-user-dir is optional (and can fail before user-dirs are configured).
    VIDEO_WALLPAPER_DIR = os.path.join(HOME, "Hidamari")

xdg_config_home = os.environ.get("XDG_CONFIG_HOME", os.path.join(HOME, ".config"))
AUTOSTART_DIR = os.path.join(xdg_config_home, "autostart")
AUTOSTART_DESKTOP_PATH = os.path.join(AUTOSTART_DIR, f"{PROJECT}.desktop")
AUTOSTART_DESKTOP_CONTENT = """[Desktop Entry]
Name=Hidamari
Exec=hidamari -b
Icon=io.github.jeffshee.Hidamari
Terminal=false
Type=Application
Categories=GTK;Utility;
StartupNotify=true
"""
AUTOSTART_DESKTOP_CONTENT_FLATPAK = """[Desktop Entry]
Name=Hidamari
Exec=/usr/bin/flatpak run --command=hidamari io.github.jeffshee.Hidamari -b
Icon=io.github.jeffshee.Hidamari
Terminal=false
Type=Application
Categories=GTK;Utility;
StartupNotify=true
X-Flatpak=io.github.jeffshee.Hidamari
"""

CONFIG_DIR = os.path.join(xdg_config_home, "hidamari")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

MODE_NULL = "MODE_NULL"
MODE_VIDEO = "MODE_VIDEO"
MODE_STREAM = "MODE_STREAM"
MODE_WEBPAGE = "MODE_WEBPAGE"

CONFIG_VERSION = 4
CONFIG_KEY_VERSION = "version"
CONFIG_KEY_MODE = "mode"
CONFIG_KEY_DATA_SOURCE = "data_source"
CONFIG_KEY_MUTE = "is_mute"
CONFIG_KEY_VOLUME = "audio_volume"
CONFIG_KEY_STATIC_WALLPAPER = "is_static_wallpaper"
CONFIG_KEY_BLUR_RADIUS = "static_wallpaper_blur_radius"
CONFIG_KEY_PAUSE_WHEN_MAXIMIZED = "is_pause_when_maximized"
CONFIG_KEY_MUTE_WHEN_MAXIMIZED = "is_mute_when_maximized"
CONFIG_KEY_FADE_DURATION_SEC = "fade_duration_sec"
CONFIG_KEY_FADE_INTERVAL = "fade_interval"
CONFIG_KEY_SYSTRAY = "is_show_systray"
CONFIG_KEY_FIRST_TIME = "is_first_time"
CONFIG_TEMPLATE = {
    CONFIG_KEY_VERSION: CONFIG_VERSION,
    CONFIG_KEY_MODE: MODE_NULL,
    CONFIG_KEY_DATA_SOURCE: None,
    CONFIG_KEY_MUTE: False,
    CONFIG_KEY_VOLUME: 50,
    CONFIG_KEY_STATIC_WALLPAPER: True,
    CONFIG_KEY_BLUR_RADIUS: 5,
    CONFIG_KEY_PAUSE_WHEN_MAXIMIZED: True,
    CONFIG_KEY_MUTE_WHEN_MAXIMIZED: False,
    CONFIG_KEY_FADE_DURATION_SEC: 1.5,
    CONFIG_KEY_FADE_INTERVAL: 0.1,
    CONFIG_KEY_SYSTRAY: False,
    CONFIG_KEY_FIRST_TIME: True,
}

from hidamari.monitor import MonitorInfo

# initialize config according to monitors
info = MonitorInfo()
monitors = info.monitors()
data_sources = {}
for monitor in monitors:
    data_sources[monitor["name"]] = ""
data_sources["Default"] = ""

CONFIG_TEMPLATE[CONFIG_KEY_DATA_SOURCE] = data_sources
