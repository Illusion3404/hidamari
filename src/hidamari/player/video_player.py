import ctypes
import glob
import logging
import os
import pathlib
import random
import subprocess
import sys
import time
from threading import Timer

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
import vlc
from gi.repository import Gdk, Gio, Gtk
from PIL import Image, ImageFilter
from pydbus import SessionBus

from hidamari.commons import (
    CONFIG_DIR,
    CONFIG_KEY_DATA_SOURCE,
    CONFIG_KEY_FADE_DURATION_SEC,
    CONFIG_KEY_FADE_INTERVAL,
    CONFIG_KEY_MODE,
    CONFIG_KEY_MUTE,
    CONFIG_KEY_MUTE_WHEN_MAXIMIZED,
    CONFIG_KEY_PAUSE_WHEN_MAXIMIZED,
    CONFIG_KEY_STATIC_WALLPAPER,
    CONFIG_KEY_VOLUME,
    DBUS_NAME_PLAYER,
    LOGGER_NAME,
    MODE_STREAM,
    MODE_VIDEO,
)
from hidamari.menu import build_menu
from hidamari.player.base_player import BasePlayer
from hidamari.player.video_options import build_vlc_options
from hidamari.utils import (
    ActiveHandler,
    ConfigUtil,
    is_flatpak,
    is_gnome,
    is_wayland,
)
from hidamari.yt_utils import get_best_audio, get_formats, get_optimal_video

logger = logging.getLogger(LOGGER_NAME)

if is_wayland():
    # TODO: Window event monitoring for GNOME Wayland is broken
    class WindowHandler:
        def __init__(self, _: callable):
            pass
else:
    from hidamari.utils import WindowHandler


def _probe_video_dimensions(path):
    """Read a local video's dimensions without letting broken files stall startup."""
    if not path or not os.path.isfile(path):
        return None, None
    try:
        output = subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=s=x:p=0",
                path,
            ],
            stderr=subprocess.DEVNULL,
            encoding="UTF-8",
            timeout=10,
        ).strip()
        width, height = output.split("x", 1)
        return int(width), int(height)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        logger.debug("[VideoProbe] Could not read dimensions for %s: %s", path, error)
        return None, None


def _stream_target_height(windows):
    """Cap high-resolution streams to avoid wasting decode work on wallpaper."""
    display_heights = [monitor.get_geometry().height for monitor in windows]
    display_height = max((height for height in display_heights if height > 0), default=720)
    configured = os.environ.get("HIDAMARI_STREAM_MAX_HEIGHT")
    if configured is not None:
        try:
            target_height = int(configured)
            if target_height < 1:
                raise ValueError
            return min(display_height, target_height)
        except ValueError:
            logger.warning("[Stream] Ignoring invalid HIDAMARI_STREAM_MAX_HEIGHT=%r", configured)
    # 1080p is a sensible ceiling for a desktop wallpaper; users with capable
    # systems can raise it with HIDAMARI_STREAM_MAX_HEIGHT.
    return min(display_height, 1080)


class Fade:
    def __init__(self):
        self.timer = None
        self.is_active = False

    def start(
        self,
        cur,
        target,
        step,
        fade_interval,
        update_callback: callable = None,
        complete_callback: callable = None,
    ):
        # Cancel any existing timer first
        self.cancel()
        self.is_active = True
        if cur == target or step == 0:
            if update_callback:
                update_callback(int(target))
            if complete_callback:
                complete_callback()
            self.is_active = False
            return
        self._fade_step(cur, target, step, fade_interval, update_callback, complete_callback)

    def _fade_step(self, cur, target, step, fade_interval, update_callback, complete_callback):
        if not self.is_active:
            return

        new_cur = cur + step
        if (step < 0 and new_cur <= target) or (step > 0 and new_cur >= target):
            new_cur = target
            if update_callback:
                update_callback(int(new_cur))
            if complete_callback:
                complete_callback()
            self.is_active = False
        else:
            if update_callback:
                update_callback(int(new_cur))
            self.timer = Timer(
                fade_interval,
                self._fade_step,
                args=[new_cur, target, step, fade_interval, update_callback, complete_callback],
            )
            self.timer.daemon = True  # Make timer daemon to prevent blocking shutdown
            self.timer.start()

    def cancel(self):
        self.is_active = False
        if self.timer:
            self.timer.cancel()
            self.timer = None


class VLCWidget(Gtk.DrawingArea):
    """
    Simple VLC widget.
    Its player can be controlled through the 'player' attribute, which
    is a vlc.MediaPlayer() instance.
    """

    __gtype_name__ = "VLCWidget"

    def __init__(self, width, height):
        Gtk.DrawingArea.__init__(self)

        # Spawn a VLC instance and create a new media player to embed. Keep
        # decode selection automatic unless a user explicitly overrides it:
        # Hidamari does not require Vulkan, and VA-API is optional on Linux.
        vlc_options = build_vlc_options()
        logger.info("[VLCWidget] LibVLC options: %s", vlc_options)
        self.instance = vlc.Instance(vlc_options)
        self.player = self.instance.media_player_new()

        def handle_embed(*args):
            self.player.set_xwindow(self.get_window().get_xid())
            return True

        # Embed and set size.
        self.connect("realize", handle_embed)
        self.set_size_request(width, height)

    def cleanup(self):
        """Cleanup VLC resources to prevent memory leaks"""
        try:
            if self.player:
                self.player.stop()
                self.player.release()
                self.player = None
            if self.instance:
                self.instance.release()
                self.instance = None
        except Exception as e:
            logger.warning(f"[VLCWidget] Cleanup error: {e}")


class PlayerWindow(Gtk.ApplicationWindow):
    def __init__(self, name, width, height, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Setup a VLC widget given the provided width and height.
        self.width = width
        self.height = height
        self.name = name
        self.__vlc_widget = VLCWidget(width, height)
        self.add(self.__vlc_widget)
        self.__vlc_widget.show()

        # These are to allow us to right click. VLC can't hijack mouse input, and probably not key inputs either in
        # Case we want to add keyboard shortcuts later on.
        self.__vlc_widget.player.video_set_mouse_input(False)
        self.__vlc_widget.player.video_set_key_input(False)

        # A timer that handling fade-in/out
        self.fade = Fade()

        self.menu = None
        self.connect("button-press-event", self._on_button_press_event)

    def update_geometry(self, width, height):
        self.width = width
        self.height = height
        self.__vlc_widget.set_size_request(width, height)
        self.resize(width, height)
        # Recompute center-crop for the new monitor dimensions once VLC knows
        # the decoded frame size.
        self.centercrop()

    def play(self):
        self.__vlc_widget.player.play()

    def play_fade(self, target, fade_duration_sec, fade_interval):
        self.play()
        cur = 0
        step = (target - cur) / (fade_duration_sec / fade_interval)
        self.fade.cancel()
        self.fade.start(
            cur=cur,
            target=target,
            step=step,
            fade_interval=fade_interval,
            update_callback=self.set_volume,
        )

    def is_playing(self):
        return self.__vlc_widget.player.is_playing()

    def pause(self):
        if self.is_playing():
            self.__vlc_widget.player.pause()

    def pause_fade(self, fade_duration_sec, fade_interval):
        cur = self.get_volume()
        target = 0
        step = (target - cur) / (fade_duration_sec / fade_interval)
        self.fade.cancel()
        self.fade.start(
            cur=cur,
            target=target,
            step=step,
            fade_interval=fade_interval,
            update_callback=self.set_volume,
            complete_callback=self.pause,
        )

    def volume_fade(self, target, fade_duration_sec, fade_interval):
        cur = self.get_volume()
        step = (target - cur) / (fade_duration_sec / fade_interval)
        self.fade.cancel()
        self.fade.start(
            cur=cur,
            target=target,
            step=step,
            fade_interval=fade_interval,
            update_callback=self.set_volume,
        )

    def media_new(self, *args):
        return self.__vlc_widget.instance.media_new(*args)

    def set_media(self, *args):
        self.__vlc_widget.player.set_media(*args)

    def set_volume(self, *args):
        self.__vlc_widget.player.audio_set_volume(*args)

    def get_volume(self):
        return self.__vlc_widget.player.audio_get_volume()

    def set_mute(self, is_mute):
        return self.__vlc_widget.player.audio_set_mute(is_mute)

    def get_position(self):
        return self.__vlc_widget.player.get_position()

    def set_position(self, *args):
        self.__vlc_widget.player.set_position(*args)

    def snapshot(self, *args):
        return self.__vlc_widget.player.video_take_snapshot(*args)

    def centercrop(self, video_width=None, video_height=None):
        # Getting dimension from libvlc is not reliable enough (need to consider timing)
        if (video_width, video_height) == (None, None):
            video_width, video_height = self.__vlc_widget.player.video_get_size()
            if video_width == 0 or video_height == 0:
                logger.warning("[CenterCrop] video_get_size is not ready yet")
                return
        logger.debug(f"[CenterCrop] Dimension {video_width}x{video_height}")
        window_ratio = self.width / self.height
        video_ratio = video_width / video_height
        if window_ratio == video_ratio:
            return
        elif video_ratio < window_ratio:
            # If window is wider than video
            # For example video ratio (4:3)=1.33..., window ratio (16:9)=1.77...
            crop_height = video_width / window_ratio
            top_offset = (video_height - crop_height) / 2
            crop_geometry = (
                f"{int(video_width)}x{int(crop_height + top_offset)}+0+{int(top_offset)}"
            )

        else:
            # If video is wider than window
            crop_width = video_height * window_ratio
            left_offset = (video_width - crop_width) / 2
            crop_geometry = (
                f"{int(crop_width + left_offset)}x{int(video_height)}+{int(left_offset)}+0"
            )

        # Crop geometry WxH+L+T: Width x Height + Left Offset + top Offset
        logger.debug(f"[CenterCrop] Crop geometry: {crop_geometry}")
        self.__vlc_widget.player.video_set_crop_geometry(crop_geometry)

    def add_audio_track(self, audio):
        self.__vlc_widget.player.add_slave(vlc.MediaSlaveType(1), audio, True)

    def _on_button_press_event(self, widget, event):
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:
            if not self.menu:
                self.menu = build_menu(MODE_VIDEO)
            self.menu.popup_at_pointer()
            return True
        return False

    def get_name(self):
        return self.name

    def cleanup(self):
        """Cleanup resources to prevent memory leaks"""
        self.fade.cancel()
        if self.__vlc_widget:
            self.__vlc_widget.cleanup()


class VideoPlayer(BasePlayer):
    """
    <node>
    <interface name='io.github.jeffshee.hidamari.player'>
        <property name="mode" type="s" access="read"/>
        <property name="data_source" type="s" access="readwrite"/>
        <property name="volume" type="i" access="readwrite"/>
        <property name="is_mute" type="b" access="readwrite"/>
        <property name="is_playing" type="b" access="read"/>
        <property name="is_paused_by_user" type="b" access="readwrite"/>
        <method name='reload_config'/>
        <method name='pause_playback'/>
        <method name='start_playback'/>
        <method name='quit_player'/>
    </interface>
    </node>
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Initialize X11 threads so VLC can use hardware decoding.
        # `libX11.so.6` fix for Fedora 33
        x11 = None
        for lib in ["libX11.so", "libX11.so.6"]:
            try:
                x11 = ctypes.cdll.LoadLibrary(lib)
            except OSError:
                pass
            if x11 is not None:
                x11.XInitThreads()
                break

        self.config = None
        self.reload_config()

        # Static wallpaper (currently for GNOME only)
        if is_gnome():
            self.original_wallpaper_uri = None
            self.original_wallpaper_uri_dark = None
            if is_flatpak():
                try:
                    self.original_wallpaper_uri = subprocess.check_output(
                        "flatpak-spawn --host gsettings get org.gnome.desktop.background picture-uri",
                        shell=True,
                        encoding="UTF-8",
                    )
                    self.original_wallpaper_uri_dark = subprocess.check_output(
                        "flatpak-spawn --host gsettings get org.gnome.desktop.background picture-uri-dark",
                        shell=True,
                        encoding="UTF-8",
                    )
                except subprocess.CalledProcessError as e:
                    logger.error(f"[StaticWallpaper] {e}")
            else:
                gso = Gio.Settings.new("org.gnome.desktop.background")
                self.original_wallpaper_uri = gso.get_string("picture-uri")
                self.original_wallpaper_uri_dark = gso.get_string("picture-uri-dark")

        # Handler should be created after everything initialized
        self.active_handler, self.window_handler = None, None
        self.is_any_maximized, self.is_any_fullscreen = False, False
        self.is_paused_by_user = False

    def new_window(self, gdk_monitor):
        rect = gdk_monitor.get_geometry()
        name = self.monitor_names.get(gdk_monitor, gdk_monitor.get_model() or "Monitor")
        return PlayerWindow(name, rect.width, rect.height, application=self)

    def do_activate(self):
        super().do_activate()
        self.data_source = self.config[CONFIG_KEY_DATA_SOURCE]

    def _on_monitor_added(self, _, gdk_monitor, *args):
        super()._on_monitor_added(_, gdk_monitor, *args)
        self.monitor_sync()

    def _on_active_changed(self, active):
        if active:
            self.pause_playback()
        else:
            if self._should_playback_start():
                self.start_playback()
            else:
                self.pause_playback()

    def _on_window_state_changed(self, state):
        self.is_any_maximized, self.is_any_fullscreen = (
            state["is_any_maximized"],
            state["is_any_fullscreen"],
        )
        logger.info(
            f"is_any_maximized: {self.is_any_maximized}, is_any_fullscreen: {self.is_any_fullscreen}"
        )

        if self.config[CONFIG_KEY_PAUSE_WHEN_MAXIMIZED]:
            if self._should_playback_start():
                self.start_playback()
            else:
                self.pause_playback()
        elif self.config[CONFIG_KEY_MUTE_WHEN_MAXIMIZED]:
            for monitor, window in self.windows.items():
                if not monitor.is_primary():
                    continue
                if self.is_any_fullscreen or self.is_any_maximized:
                    window.volume_fade(
                        target=0,
                        fade_duration_sec=self.config[CONFIG_KEY_FADE_DURATION_SEC],
                        fade_interval=self.config[CONFIG_KEY_FADE_INTERVAL],
                    )
                else:
                    window.volume_fade(
                        target=self.volume,
                        fade_duration_sec=self.config[CONFIG_KEY_FADE_DURATION_SEC],
                        fade_interval=self.config[CONFIG_KEY_FADE_INTERVAL],
                    )

    def _should_playback_start(self):
        if self.config[CONFIG_KEY_PAUSE_WHEN_MAXIMIZED] and (
            self.is_any_maximized or self.is_any_fullscreen
        ):
            return False
        if self.is_paused_by_user:
            return False
        return True

    @property
    def mode(self):
        return self.config[CONFIG_KEY_MODE]

    @property
    def data_source(self):
        return self.config[CONFIG_KEY_DATA_SOURCE]

    @data_source.setter
    def data_source(self, data_source):
        sources = data_source if isinstance(data_source, dict) else {}
        self.config[CONFIG_KEY_DATA_SOURCE] = sources

        if self.mode == MODE_VIDEO:
            default_source = sources.get("Default") or ""
            if not default_source:
                logger.warning("[Video] No local video is selected")
                self.set_original_wallpaper()
                return

            # Probe each distinct file once; a per-monitor configuration often
            # points multiple displays at the same video.
            dimensions = {}
            for source in set(value for value in sources.values() if value):
                dimensions[source] = _probe_video_dimensions(source)

            for monitor, window in self.windows.items():
                model = self.monitor_names.get(monitor, monitor.get_model() or "Monitor")
                source = sources.get(model) or default_source
                if not source:
                    continue
                logger.info("Setting source %s to %s", source, model)
                media = window.media_new(source)
                # Repeat the media itself. LibVLC's --repeat/--loop options do
                # not reliably loop an embedded media player.
                media.add_option("input-repeat=65535")
                # Only the primary display emits audio.
                if not monitor.is_primary():
                    media.add_option("no-audio")
                window.set_media(media)
                window.set_position(0.0)
                width, height = dimensions.get(source, (None, None))
                window.centercrop(width, height)

        elif self.mode == MODE_STREAM:
            source = sources.get("Default")
            if not source:
                logger.warning("[Stream] No stream URL is configured")
                return
            try:
                formats = get_formats(source)
                max_height = _stream_target_height(self.windows)
                video_url, video_width, video_height = get_optimal_video(formats, max_height)
                audio_url = get_best_audio(formats)
            except Exception:
                # A stale URL, a removed format, or a temporary network failure
                # should not crash the GTK player process.
                logger.exception("[Stream] Could not prepare stream: %s", source)
                return

            logger.info(
                "[Stream] Selected %sx%s video at or below %sp; H.264 is preferred when available",
                video_width,
                video_height,
                max_height,
            )
            for monitor, window in self.windows.items():
                media = window.media_new(video_url)
                media.add_option("input-repeat=65535")
                if not monitor.is_primary():
                    # Some streaming formats include audio; avoid duplicate
                    # audio playback on secondary monitors.
                    media.add_option("no-audio")
                window.set_media(media)
                if monitor.is_primary() and audio_url:
                    window.add_audio_track(audio_url)
                window.set_position(0.0)
                window.centercrop(video_width, video_height)
        else:
            raise ValueError("Invalid mode")

        self.volume = self.config[CONFIG_KEY_VOLUME]
        self.is_mute = self.config[CONFIG_KEY_MUTE]
        self.start_playback()

        # Everything is initialized. Create handlers if haven't (singleton pattern).
        if not self.active_handler:
            self.active_handler = ActiveHandler(self._on_active_changed)
        if not self.window_handler and not is_wayland():
            # Only create WindowHandler on X11, not Wayland.
            self.window_handler = WindowHandler(self._on_window_state_changed)

        if self.config[CONFIG_KEY_STATIC_WALLPAPER] and self.mode == MODE_VIDEO:
            self.set_static_wallpaper()
        else:
            self.set_original_wallpaper()

    @property
    def volume(self):
        return self.config[CONFIG_KEY_VOLUME]

    @volume.setter
    def volume(self, volume):
        self.config[CONFIG_KEY_VOLUME] = volume
        for monitor in self.windows:
            if monitor.is_primary():
                self.windows[monitor].set_volume(volume)

    @property
    def is_mute(self):
        return self.config[CONFIG_KEY_MUTE]

    @is_mute.setter
    def is_mute(self, is_mute):
        self.config[CONFIG_KEY_MUTE] = is_mute
        for monitor, window in self.windows.items():
            if monitor.is_primary():
                window.set_mute(is_mute)

    @property
    def is_playing(self):
        return not self.is_paused_by_user

    def pause_playback(self):
        for _monitor, window in self.windows.items():
            window.pause_fade(
                fade_duration_sec=self.config[CONFIG_KEY_FADE_DURATION_SEC],
                fade_interval=self.config[CONFIG_KEY_FADE_INTERVAL],
            )

    def start_playback(self):
        if self._should_playback_start():
            for _monitor, window in self.windows.items():
                window.play_fade(
                    target=self.volume,
                    fade_duration_sec=self.config[CONFIG_KEY_FADE_DURATION_SEC],
                    fade_interval=self.config[CONFIG_KEY_FADE_INTERVAL],
                )

    def monitor_sync(self):
        primary_monitor = None
        for monitor in self.windows:
            if monitor.is_primary():
                primary_monitor = monitor
                break
        if primary_monitor:
            primary_window = self.windows[primary_monitor]
            for monitor, window in self.windows.items():
                if monitor == primary_monitor or window is None:
                    continue
                # LibVLC requires playback to be enabled before seeking.
                window.play()
                window.set_position(primary_window.get_position())
                if primary_window.is_playing():
                    window.play()
                else:
                    window.pause()

    def set_static_wallpaper(self):
        # Currently for GNOME only
        if not is_gnome():
            return
        # Get the duration of the video
        source = self.data_source.get("Default")
        if not source or not os.path.isfile(source):
            return
        try:
            duration = float(
                subprocess.check_output(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        source,
                    ],
                    encoding="UTF-8",
                    stderr=subprocess.DEVNULL,
                    timeout=10,
                )
            )
        except (OSError, subprocess.SubprocessError, ValueError) as error:
            logger.warning("[StaticWallpaper] Could not read video duration: %s", error)
            return
        # Find a representative point in the video.
        ss = time.strftime("%H:%M:%S", time.gmtime(max(0, duration) / 3.14))
        static_wallpaper_path = os.path.join(
            CONFIG_DIR, f"static-{random.randint(0, 999999):06d}.png"
        )
        display_width = max(
            (monitor.get_geometry().width for monitor in self.windows), default=1280
        )
        display_height = max(
            (monitor.get_geometry().height for monitor in self.windows), default=720
        )
        target_width = max(1, min(display_width, 1920))
        target_height = max(1, min(display_height, 1080))
        try:
            ret = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-ss",
                    ss,
                    "-i",
                    source,
                    "-vf",
                    f"scale={target_width}:{target_height}:force_original_aspect_ratio=decrease",
                    "-frames:v",
                    "1",
                    static_wallpaper_path,
                ],
                check=False,
                timeout=30,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
        except (OSError, subprocess.SubprocessError) as error:
            logger.warning("[StaticWallpaper] Frame extraction failed: %s", error)
            return
        if ret.returncode == 0 and os.path.isfile(static_wallpaper_path):
            try:
                with Image.open(static_wallpaper_path) as image:
                    blur_wallpaper = image.filter(
                        ImageFilter.GaussianBlur(self.config["static_wallpaper_blur_radius"])
                    )
                    blur_wallpaper.save(static_wallpaper_path)
            except OSError as error:
                logger.warning("[StaticWallpaper] Could not process extracted frame: %s", error)
                return
            static_wallpaper_uri = pathlib.Path(static_wallpaper_path).resolve().as_uri()
            if is_flatpak():
                try:
                    subprocess.run(
                        [
                            "flatpak-spawn",
                            "--host",
                            "gsettings",
                            "set",
                            "org.gnome.desktop.background",
                            "picture-uri",
                            static_wallpaper_uri,
                        ],
                        shell=False,
                    )
                    subprocess.run(
                        [
                            "flatpak-spawn",
                            "--host",
                            "gsettings",
                            "set",
                            "org.gnome.desktop.background",
                            "picture-uri-dark",
                            static_wallpaper_uri,
                        ],
                        shell=False,
                    )
                except subprocess.CalledProcessError as e:
                    logger.error(f"[StaticWallpaper] {e}")
            else:
                gso = Gio.Settings.new("org.gnome.desktop.background")
                gso.set_string("picture-uri", static_wallpaper_uri)
                gso.set_string("picture-uri-dark", static_wallpaper_uri)

    def set_original_wallpaper(self):
        # Currently for GNOME only
        if not is_gnome():
            return
        if is_flatpak():
            try:
                if self.original_wallpaper_uri is not None:
                    subprocess.run(
                        [
                            "flatpak-spawn",
                            "--host",
                            "gsettings",
                            "set",
                            "org.gnome.desktop.background",
                            "picture-uri",
                            self.original_wallpaper_uri,
                        ],
                        shell=False,
                    )
                if self.original_wallpaper_uri_dark is not None:
                    subprocess.run(
                        [
                            "flatpak-spawn",
                            "--host",
                            "gsettings",
                            "set",
                            "org.gnome.desktop.background",
                            "picture-uri-dark",
                            self.original_wallpaper_uri_dark,
                        ],
                        shell=False,
                    )
            except subprocess.CalledProcessError as e:
                logger.error(f"[StaticWallpaper] {e}")
        else:
            gso = Gio.Settings.new("org.gnome.desktop.background")
            gso.set_string("picture-uri", self.original_wallpaper_uri)
            gso.set_string("picture-uri-dark", self.original_wallpaper_uri_dark)
        # Purge the generated static wallpaper (and leftover if any)
        for f in glob.glob(os.path.join(CONFIG_DIR, "static-*.png")):
            os.remove(f)

    def reload_config(self):
        self.config = ConfigUtil().load()

    def quit_player(self):
        self.set_original_wallpaper()

        # Cleanup handlers
        if self.active_handler:
            self.active_handler.cleanup()
            self.active_handler = None

        if self.window_handler:
            self.window_handler.cleanup()
            self.window_handler = None

        # Cleanup all windows
        for _monitor, window in self.windows.items():
            if window:
                window.cleanup()

        super().quit_player()


def main():
    bus = SessionBus()
    app = VideoPlayer()
    try:
        bus.publish(DBUS_NAME_PLAYER, app)
    except RuntimeError as e:
        logger.error(e)
    app.run(sys.argv)


if __name__ == "__main__":
    main()
