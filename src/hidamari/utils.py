import copy
import gettext
import json
import locale
import logging
import math
import os
import tempfile
from pprint import pformat

import gi

gi.require_version("Wnck", "3.0")
import pydbus
from gi.repository import Gio, GLib, Wnck

from hidamari.commons import (
    AUTOSTART_DESKTOP_CONTENT,
    AUTOSTART_DESKTOP_CONTENT_FLATPAK,
    AUTOSTART_DESKTOP_PATH,
    AUTOSTART_DIR,
    CONFIG_DIR,
    CONFIG_KEY_BLUR_RADIUS,
    CONFIG_KEY_DATA_SOURCE,
    CONFIG_KEY_FADE_DURATION_SEC,
    CONFIG_KEY_FADE_INTERVAL,
    CONFIG_KEY_FIRST_TIME,
    CONFIG_KEY_MODE,
    CONFIG_KEY_MUTE,
    CONFIG_KEY_MUTE_WHEN_MAXIMIZED,
    CONFIG_KEY_PAUSE_WHEN_MAXIMIZED,
    CONFIG_KEY_STATIC_WALLPAPER,
    CONFIG_KEY_SYSTRAY,
    CONFIG_KEY_VOLUME,
    CONFIG_PATH,
    CONFIG_TEMPLATE,
    CONFIG_VERSION,
    LOGGER_NAME,
    MODE_NULL,
    MODE_STREAM,
    MODE_VIDEO,
    MODE_WEBPAGE,
    TRANSLATION_DOMAIN,
    VIDEO_WALLPAPER_DIR,
)

logger = logging.getLogger(LOGGER_NAME)


def init_translations(localedir):
    """Bind the gettext text domain for the current process.

    The forkserver children (GUI, systray) don't inherit the launcher's gettext
    setup, so each entry point binds it itself. We bind at both the C-library
    level (for GtkBuilder/.ui strings) and the Python level (for _()); missing
    catalogs simply fall back to the original strings, so this can't crash.
    """
    try:
        locale.bindtextdomain(TRANSLATION_DOMAIN, localedir)
        locale.textdomain(TRANSLATION_DOMAIN)
    except (AttributeError, OSError) as e:
        logger.debug("[i18n] C locale bind skipped: %s", e)
    gettext.bindtextdomain(TRANSLATION_DOMAIN, localedir)
    gettext.textdomain(TRANSLATION_DOMAIN)


def is_gnome():
    """
    Check if current DE is GNOME or not.
    On Ubuntu 20.04, $XDG_CURRENT_DESKTOP = ubuntu:GNOME
    On Fedora 34, $XDG_CURRENT_DESKTOP = GNOME
    Hence we do the detection by looking for the word "gnome"
    """
    return "gnome" in str(os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()


def is_wayland():
    """
    Check if current session is Wayland or not.
    $XDG_SESSION_TYPE = x11 | wayland
    """
    return os.environ.get("XDG_SESSION_TYPE") == "wayland"


def is_flatpak():
    """
    Check if Hidamari is a Flatpak
    Reference:
    https://gitlab.gnome.org/jrb/crosswords/-/blob/master/src/crosswords-init.c#L179
    """
    return os.path.isfile("/.flatpak-info")


def setup_autostart(autostart):
    if is_flatpak():
        """
        Use portal to autostart for Flatpak
        Documentation:
        https://libportal.org/method.Portal.request_background.html
        https://libportal.org/method.Portal.request_background_finish.html
        """

        gi.require_version("Xdp", "1.0")
        from gi.repository import Xdp

        xdp = Xdp.Portal.new()

        # Request Autostart
        xdp.request_background(
            None,  # parent
            "Autostart Hidamari in background",  # reason
            ["hidamari", "-b"],  # commandline
            Xdp.BackgroundFlags.AUTOSTART if autostart else Xdp.BackgroundFlags.NONE,  # flags
            None,  # cancellable
            lambda portal, result, user_data: logger.debug(
                f"[Utils] autostart={autostart}, request_background sucess={portal.request_background_finish(result)}"
            ),  # callback
            None,  # user_data
        )

    os.makedirs(AUTOSTART_DIR, exist_ok=True)
    logger.debug(f"[Utils] autostart={autostart}, path={AUTOSTART_DESKTOP_PATH}")
    if autostart:
        with open(AUTOSTART_DESKTOP_PATH, mode="w") as f:
            if is_flatpak():
                # Write files to the sandbox as well, for the following reasons:
                # (1) So that we know if autostart is enabled by looking the file in sandbox
                # (2) Acts as a fallback in case the portal doesn't work
                f.write(AUTOSTART_DESKTOP_CONTENT_FLATPAK)
            else:
                f.write(AUTOSTART_DESKTOP_CONTENT)
    else:
        if os.path.isfile(AUTOSTART_DESKTOP_PATH):
            os.remove(AUTOSTART_DESKTOP_PATH)


def get_video_paths():
    file_list = []
    for filename in os.listdir(VIDEO_WALLPAPER_DIR):
        filepath = os.path.join(VIDEO_WALLPAPER_DIR, filename)
        file = Gio.file_new_for_path(filepath)
        info = file.query_info("standard::content-type", Gio.FileQueryInfoFlags.NONE, None)
        mime_type = info.get_content_type()
        if "video" in mime_type:
            file_list.append(filepath)
    return sorted(file_list)


"""
GNOME extension utils
"""


def gnome_extension_is_enabled(extension_name: str):
    gnome_ext = pydbus.SessionBus().get("org.gnome.Shell.Extensions")
    info: dict = gnome_ext.GetExtensionInfo(extension_name)
    return info["state"] == 1  # ENABLE = 1


def gnome_extension_set_enable(extension_name: str):
    gnome_ext = pydbus.SessionBus().get("org.gnome.Shell.Extensions")
    success: bool = gnome_ext.EnableExtension(extension_name)
    return success


def gnome_extension_set_disable(extension_name: str):
    gnome_ext = pydbus.SessionBus().get("org.gnome.Shell.Extensions")
    success: bool = gnome_ext.DisableExtension(extension_name)
    return success


def gnome_extension_is_installed(extension_name: str):
    gnome_ext = pydbus.SessionBus().get("org.gnome.Shell.Extensions")
    installed: dict = gnome_ext.ListExtensions()
    return extension_name in installed.keys()


def gnome_desktop_icon_workaround():
    """
    Workaround for GNOME desktop icon extensions not displaying the icons on top of Hidamari.
    Call this right after the wallpaper is shown.
    """
    if not is_gnome():
        return
    extension_list = [
        "ding@rastersoft.com",
        "desktopicons-neo@darkdemon",
        "gtk4-ding@smedius.gitlab.com",
        "zorin-desktop-icons@zorinos.com",
    ]
    for ext in extension_list:
        # Check if installed and enabled
        if gnome_extension_is_installed(ext) and gnome_extension_is_enabled(ext):
            # Reload the extension
            logger.info(f"[Utils] Apply workaround for {ext}")
            gnome_extension_set_disable(ext)
            gnome_extension_set_enable(ext)


"""
Handlers
"""


class ActiveHandler:
    """
    Handler for monitoring screen lock
    GNOME:
    https://gitlab.gnome.org/GNOME/gnome-shell/-/blob/main/data/dbus-interfaces/org.gnome.ScreenSaver.xml
    Cinamon:
    https://github.com/linuxmint/cinnamon-screensaver/blob/master/libcscreensaver/org.cinnamon.ScreenSaver.xml
    Freedesktop:
    https://github.com/KDE/kscreenlocker/blob/master/dbus/org.freedesktop.ScreenSaver.xml
    """

    def __init__(self, on_active_changed: callable):
        self.session_bus = pydbus.SessionBus()
        self.proxies = []
        self.signal_subscriptions = []

        screensaver_list = [
            "org.gnome.ScreenSaver",
            "org.cinnamon.ScreenSaver",
            "org.freedesktop.ScreenSaver",
        ]
        for s in screensaver_list:
            try:
                proxy = self.session_bus.get(s)
                # Store proxy reference to prevent garbage collection
                self.proxies.append(proxy)
                subscription = proxy.ActiveChanged.connect(on_active_changed)
                self.signal_subscriptions.append((proxy, subscription))
            except GLib.Error:
                pass

    def cleanup(self):
        """Cleanup signal subscriptions"""
        # pydbus has no disconnect; connections drop when the proxies are GC'd
        self.signal_subscriptions.clear()
        self.proxies.clear()


class EndSessionHandler:
    """
    Handler for monitoring end session
    References:
    https://github.com/backloop/gendsession

    PrepareForShutdown() signal from logind is not handled
    https://gitlab.gnome.org/GNOME/gnome-shell/-/issues/787
    """

    def __init__(self, on_end_session: callable):
        self.on_end_session = on_end_session

        if is_gnome():
            session_bus = pydbus.SessionBus()
            proxy = session_bus.get("org.gnome.SessionManager")
            client_id = proxy.RegisterClient("", "")
            self.session_client = session_bus.get("org.gnome.SessionManager", client_id)
            self.session_client.QueryEndSession.connect(self.__query_end_session_handler_gnome)
            self.session_client.EndSession.connect(self.__end_session_handler_gnome)
        else:
            system_bus = pydbus.SystemBus()
            proxy = system_bus.get(".login1")
            proxy.PrepareForShutdown.connect(self.__end_session_handler)

    def __end_session_response_gnome(self, ok=True):
        if ok:
            self.session_client.EndSessionResponse(True, "")
        else:
            self.session_client.EndSessionResponse(False, "Not ready")

    def __query_end_session_handler_gnome(self, flags):
        # Ignore flags, always agree on the QueryEndSesion
        self.__end_session_response_gnome(True)

    def __end_session_handler_gnome(self, flags):
        logger.debug("[EndSessionHandler] called")
        self.on_end_session()
        self.__end_session_response_gnome(True)

    def __end_session_handler(self, *_):
        logger.debug("[EndSessionHandler] called")
        self.on_end_session()


class WindowHandler:
    """
    Handler for monitoring window events (maximized and fullscreen mode) for X11
    """

    def __init__(self, on_window_state_changed: callable):
        self.on_window_state_changed = on_window_state_changed
        self.screen = Wnck.Screen.get_default()
        self.screen.force_update()

        # Store signal handler IDs for cleanup
        self.signal_handlers = []
        self.window_signal_handlers = {}

        # Connect screen signals and store handler IDs
        handler_id = self.screen.connect("window-opened", self.window_opened, None)
        self.signal_handlers.append((self.screen, handler_id))

        handler_id = self.screen.connect("window-closed", self.eval, None)
        self.signal_handlers.append((self.screen, handler_id))

        handler_id = self.screen.connect("active-workspace-changed", self.eval, None)
        self.signal_handlers.append((self.screen, handler_id))

        # Connect to existing windows
        for window in self.screen.get_windows():
            self._connect_window(window)

        self.prev_state = None
        # Initial check
        self.eval()

    def _connect_window(self, window):
        """Connect to a window and store the handler ID"""
        if window not in self.window_signal_handlers:
            handler_id = window.connect("state-changed", self.eval, None)
            self.window_signal_handlers[window] = handler_id

    def window_opened(self, screen, window, _):
        self._connect_window(window)

    def eval(self, *args):
        # TODO: #28 (Wallpaper stops animating on other monitor when app maximized on other)
        is_changed = False

        is_any_maximized, is_any_fullscreen = False, False
        for window in self.screen.get_windows():
            base_state = not Wnck.Window.is_minimized(window) and Wnck.Window.is_on_workspace(
                window, self.screen.get_active_workspace()
            )
            is_maximized = Wnck.Window.is_maximized(window) and base_state
            is_fullscreen = Wnck.Window.is_fullscreen(window) and base_state
            if is_maximized is True:
                is_any_maximized = True
            if is_fullscreen is True:
                is_any_fullscreen = True

        cur_state = {"is_any_maximized": is_any_maximized, "is_any_fullscreen": is_any_fullscreen}
        if self.prev_state is None or self.prev_state != cur_state:
            is_changed = True
            self.prev_state = cur_state

        if is_changed:
            self.on_window_state_changed(
                {"is_any_maximized": is_any_maximized, "is_any_fullscreen": is_any_fullscreen}
            )
            logger.debug(f"[WindowHandler] {cur_state}")

    def cleanup(self):
        """Cleanup all signal handlers to prevent memory leaks"""
        # Disconnect screen signals
        for obj, handler_id in self.signal_handlers:
            try:
                obj.disconnect(handler_id)
            except Exception as e:
                logger.warning(f"[WindowHandler] Error disconnecting screen signal: {e}")
        self.signal_handlers.clear()

        # Disconnect window signals
        for window, handler_id in self.window_signal_handlers.items():
            try:
                window.disconnect(handler_id)
            except Exception as e:
                logger.warning(f"[WindowHandler] Error disconnecting window signal: {e}")
        self.window_signal_handlers.clear()


class ConfigUtil:
    @staticmethod
    def _template():
        # CONFIG_TEMPLATE is also used as a module-level default. Never return
        # its nested monitor dictionary by reference: callers mutate configs.
        return copy.deepcopy(CONFIG_TEMPLATE)

    def generate_template(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        config = self._template()
        self.save(config)
        return config

    @staticmethod
    def _check(config: dict):
        """Reject malformed configuration before any runtime code uses it."""
        if not isinstance(config, dict):
            return False
        if config.get("version") != CONFIG_VERSION:
            return False
        if not all(key in config for key in CONFIG_TEMPLATE):
            return False
        if config.get(CONFIG_KEY_MODE) not in (MODE_NULL, MODE_VIDEO, MODE_STREAM, MODE_WEBPAGE):
            return False

        data_sources = config.get(CONFIG_KEY_DATA_SOURCE)
        if not isinstance(data_sources, dict):
            return False
        if any(not isinstance(value, (str, type(None))) for value in data_sources.values()):
            return False

        boolean_keys = (
            CONFIG_KEY_MUTE,
            CONFIG_KEY_STATIC_WALLPAPER,
            CONFIG_KEY_PAUSE_WHEN_MAXIMIZED,
            CONFIG_KEY_MUTE_WHEN_MAXIMIZED,
            CONFIG_KEY_SYSTRAY,
            CONFIG_KEY_FIRST_TIME,
        )
        if any(type(config.get(key)) is not bool for key in boolean_keys):
            return False
        if (
            type(config.get(CONFIG_KEY_VOLUME)) is not int
            or not 0 <= config[CONFIG_KEY_VOLUME] <= 100
        ):
            return False
        if (
            type(config.get(CONFIG_KEY_BLUR_RADIUS)) is not int
            or not 0 <= config[CONFIG_KEY_BLUR_RADIUS] <= 20
        ):
            return False
        for key in (CONFIG_KEY_FADE_DURATION_SEC, CONFIG_KEY_FADE_INTERVAL):
            value = config.get(key)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                return False
        return True

    def _invalid(self):
        logger.warning("[Config] Invalid configuration. Generating a fresh one.")
        return self.generate_template()

    def _migrateV3To4(self, config: dict):
        logger.info("[Config] Migrating configuration from version 3 to 4")
        migrated = self._template()
        for key in migrated:
            if key in config and key not in (CONFIG_KEY_DATA_SOURCE, "version"):
                migrated[key] = config[key]

        old_source = config.get(CONFIG_KEY_DATA_SOURCE, "")
        data_sources = migrated[CONFIG_KEY_DATA_SOURCE]
        if isinstance(old_source, dict):
            data_sources.update(
                {key: value for key, value in old_source.items() if isinstance(value, str)}
            )
        elif isinstance(old_source, str):
            data_sources["Default"] = old_source
        migrated[CONFIG_KEY_DATA_SOURCE] = data_sources
        migrated[CONFIG_KEY_PAUSE_WHEN_MAXIMIZED] = config.get(
            "is_detect_maximized", migrated[CONFIG_KEY_PAUSE_WHEN_MAXIMIZED]
        )
        migrated[CONFIG_KEY_MUTE_WHEN_MAXIMIZED] = CONFIG_TEMPLATE[CONFIG_KEY_MUTE_WHEN_MAXIMIZED]
        migrated["version"] = CONFIG_VERSION
        self.save(migrated)
        return migrated

    def _checkMissingMonitors(self, old_config: dict, template: dict):
        data_sources = old_config.get(CONFIG_KEY_DATA_SOURCE)
        if not isinstance(data_sources, dict):
            return
        missing_monitors = set(template[CONFIG_KEY_DATA_SOURCE]) - set(data_sources)
        if missing_monitors:
            logger.info("[Config] Adding defaults for %s new monitor(s)", len(missing_monitors))
            for key in missing_monitors:
                data_sources[key] = data_sources.get("Default", "")
            self.save(old_config)

    def _checkDefaultSource(self, config: dict):
        data_sources = config.get(CONFIG_KEY_DATA_SOURCE, {})
        default_source = data_sources.get("Default") or ""
        if config.get("mode") != MODE_VIDEO or (default_source and os.path.isfile(default_source)):
            return

        logger.info("[Config] Default video is missing; searching configured monitor sources")
        for value in data_sources.values():
            if isinstance(value, str) and value and os.path.isfile(value):
                data_sources["Default"] = value
                self.save(config)
                return

    def load(self):
        if os.path.isfile(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, encoding="utf-8") as file:
                    config = json.load(file)
            except (OSError, UnicodeError, json.decoder.JSONDecodeError) as error:
                logger.warning("[Config] Could not read %s: %s", CONFIG_PATH, error)
                return self._invalid()

            if not isinstance(config, dict):
                return self._invalid()
            if config.get("version") == 3:
                config = self._migrateV3To4(config)
            if not self._check(config):
                return self._invalid()

            # The old player could have written null when no source was passed
            # during startup. Treat that as an empty selection, not a corrupt
            # entire profile.
            data_sources = config[CONFIG_KEY_DATA_SOURCE]
            for key, value in tuple(data_sources.items()):
                if value is None:
                    data_sources[key] = ""
            self._checkDefaultSource(config)
            self._checkMissingMonitors(config, self._template())

            logs = [
                "--------- Config ---------",
                pformat(config, indent=3),
                "--------------------------",
            ]
            logger.debug("[Config] Loaded %s\n%s", CONFIG_PATH, "\n".join(logs))
            return config
        return self._invalid()

    def save(self, config):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        old_config = None
        try:
            with open(CONFIG_PATH, encoding="utf-8") as file:
                old_config = json.load(file)
        except (OSError, UnicodeError, json.decoder.JSONDecodeError):
            pass

        # Skip needless disk writes, but don't compare invalid/old config files.
        if self._check(old_config) and old_config == config:
            return

        try:
            json_str = json.dumps(config, indent=3) + "\n"
            fd, temporary_path = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=CONFIG_DIR)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as file:
                    file.write(json_str)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary_path, CONFIG_PATH)
            finally:
                if os.path.exists(temporary_path):
                    os.unlink(temporary_path)
        except OSError as error:
            logger.error("[Config] Could not save %s: %s", CONFIG_PATH, error)
            return

        logs = [
            "--------- Config ---------",
            pformat(config, indent=3),
            "--------------------------",
        ]
        logger.debug("[Config] Saved %s\n%s", CONFIG_PATH, "\n".join(logs))
