"""Lightweight diagnostics for Linux graphics and video playback support.

This module intentionally has no GTK, VLC, or other optional imports so
``hidamari --diagnostics`` can run when the graphical application cannot.
"""

import ctypes.util
import glob
import os
import platform
import shutil
import subprocess
import sys
from importlib.util import find_spec


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as file:
            return file.read().strip()
    except OSError:
        return ""


def _os_name():
    try:
        info = platform.freedesktop_os_release()
    except (AttributeError, OSError):
        info = {}
    return info.get("PRETTY_NAME") or info.get("NAME") or sys.platform


def _cpu_name():
    processor_id = ""
    for line in _read_text("/proc/cpuinfo").splitlines():
        key, separator, value = line.partition(":")
        if not separator or not value.strip():
            continue
        key = key.strip().lower()
        if key in ("model name", "hardware"):
            return value.strip()
        if key == "processor" and not processor_id:
            processor_id = value.strip()
    return platform.processor() or processor_id or "unknown"


def _render_devices():
    devices = []
    for node in sorted(glob.glob("/dev/dri/renderD*")):
        sysfs_device = f"/sys/class/drm/{os.path.basename(node)}/device"
        driver_path = os.path.realpath(os.path.join(sysfs_device, "driver"))
        vendor = _read_text(os.path.join(sysfs_device, "vendor"))
        device = _read_text(os.path.join(sysfs_device, "device"))
        gpu_name = _read_text(os.path.join(sysfs_device, "product_name")) or _read_text(
            os.path.join(sysfs_device, "name")
        )
        details = [os.path.basename(driver_path)]
        if gpu_name:
            details.append(gpu_name)
        if vendor or device:
            details.append(f"PCI {vendor or 'unknown'}:{device or 'unknown'}")
        devices.append((node, ", ".join(details)))
    return devices


def _vaapi_report(render_devices):
    vainfo = shutil.which("vainfo")
    if vainfo is None:
        return ["VA-API: vainfo not installed (optional package: libva-utils)"]
    if not render_devices:
        return ["VA-API: no /dev/dri/renderD* device found"]

    lines = []
    for node, _details in render_devices:
        try:
            result = subprocess.run(
                [vainfo, "--display", "drm", "--device", node],
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            lines.append(f"VA-API ({node}): probe failed: {error}")
            continue

        output = f"{result.stdout}\n{result.stderr}"
        profiles = [
            line.strip()
            for line in output.splitlines()
            if "VAProfile" in line and "VAEntrypointVLD" in line
        ]
        if result.returncode == 0:
            lines.append(f"VA-API ({node}): available")
            h264_profiles = [line for line in profiles if "H264" in line]
            if h264_profiles:
                lines.append("  H.264 decode: " + "; ".join(h264_profiles))
            elif profiles:
                lines.append("  Decode profiles: " + "; ".join(profiles))
            else:
                lines.append("  No video decode profiles were reported")
        else:
            message = next(
                (line.strip() for line in output.splitlines() if line.strip()),
                f"vainfo exited with status {result.returncode}",
            )
            lines.append(f"VA-API ({node}): unavailable: {message}")
    return lines


def collect_diagnostics():
    """Return a concise, privacy-conscious report of local graphics support."""
    render_devices = _render_devices()
    session_type = os.environ.get("XDG_SESSION_TYPE", "unknown")
    desktop = os.environ.get("XDG_CURRENT_DESKTOP", "unknown")
    display = os.environ.get("DISPLAY", "not set")
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "not set")

    lines = [
        "Hidamari system diagnostics",
        f"OS: {_os_name()}",
        f"Kernel: {platform.release()}",
        f"CPU: {_cpu_name()}",
        f"Python: {platform.python_version()}",
        f"Desktop: {desktop}",
        f"Session: {session_type}",
        f"DISPLAY: {display}",
        f"WAYLAND_DISPLAY: {wayland_display}",
        f"GDK_BACKEND (inherited): {os.environ.get('GDK_BACKEND', 'not set')}",
        "Vulkan: not required by Hidamari (video is rendered through X11/XWayland and VLC)",
    ]

    if render_devices:
        lines.append("DRM render devices:")
        lines.extend(f"  {node}: {details}" for node, details in render_devices)
    else:
        lines.append("DRM render devices: none found")

    lines.extend(_vaapi_report(render_devices))
    lines.append(f"VLC Python bindings: {'installed' if find_spec('vlc') else 'not found'}")
    lines.append(f"libVLC shared library: {ctypes.util.find_library('vlc') or 'not found'}")
    lines.append(f"ffmpeg: {shutil.which('ffmpeg') or 'not found'}")
    lines.append(f"ffprobe: {shutil.which('ffprobe') or 'not found'}")
    lines.append("")
    lines.append("For playback, Hidamari uses VLC's automatic decoder by default.")
    lines.append(
        "On AMD hardware, install a working Mesa VA-API driver and verify H.264 decode above."
    )
    return lines


def print_diagnostics():
    print("\n".join(collect_diagnostics()))
