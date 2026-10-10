import argparse
import logging
import os
import sys


def main(version="devel", pkgdatadir="/usr/share/hidamari", localedir="/usr/share/locale"):
    parser = argparse.ArgumentParser(description=f"Hidamari v{version}")
    parser.add_argument(
        "-p",
        "--pause",
        dest="p",
        type=int,
        default=0,
        help="Add pause before launching Hidamari. [sec]",
    )
    parser.add_argument(
        "-b", "--background", action="store_true", help="Launch only the live wallpaper."
    )
    parser.add_argument("-d", "--debug", action="store_true", help="Print debug messages.")
    parser.add_argument("-r", "--reset", action="store_true", help="Reset user configuration.")
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="Print Linux, graphics, VA-API, and VLC diagnostics, then exit.",
    )
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    # Diagnostics deliberately run before importing GTK or the rest of the app,
    # so this command is useful even when the graphical stack cannot start.
    if args.diagnostics:
        from hidamari.diagnostics import print_diagnostics

        print_diagnostics()
        return 0

    # LibVLC embeds its video surface using the X11 window id API. Force GTK to
    # use X11 (XWayland in a Wayland session) before importing any GI modules:
    # importing Gdk can initialize the display, so setting this in a later
    # function body after importing server.py is too late on some desktops.
    os.environ["GDK_BACKEND"] = "x11"
    # Suppress VLC's own log stream; Hidamari controls application logging.
    os.environ["VLC_VERBOSE"] = "-1"

    # Import only after configuring the GTK backend. The server imports Gdk and
    # initializes monitor information at module load time.
    from hidamari import server
    from hidamari.commons import LOGGER_NAME, VIDEO_WALLPAPER_DIR
    from hidamari.utils import is_flatpak, is_gnome, is_wayland

    app_logger = logging.getLogger(LOGGER_NAME)

    # Log system information
    sys_info = [
        "--- System information ---",
        f"is_gnome = {is_gnome()}",
        f"is_wayland = {is_wayland()}",
        f"is_flatpak = {is_flatpak()}",
        f"GDK_BACKEND = {os.environ['GDK_BACKEND']}",
        "--------------------------",
    ]
    app_logger.info("Hidamari v%s\n%s", version, "\n".join(sys_info))
    app_logger.info("[Args] %s", vars(args))

    # Ensure the video directory resolved by commons.py exists.
    os.makedirs(VIDEO_WALLPAPER_DIR, exist_ok=True)

    # Clear sys.argv as it has influence to the Gtk.Application.
    sys.argv = [sys.argv[0]]
    server.main(version, pkgdatadir, localedir, args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
