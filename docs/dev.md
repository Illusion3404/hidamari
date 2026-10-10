# Development Note

Hidamari can be built using two methods: "Build and Install" and "Build as Flatpak."

1. **Build and Install**
   - This method requires you to have dependencies installed on your system.
   - It installs all components, including scripts, icons, and a desktop file, into a prefix (`~/.local` by default).
   - If your distro has the necessary packages, "Build and Install" is the quickest Hidamari setup.

2. **Build as Flatpak**
   - This method doesn't require you to have dependencies installed on your system.
   - Instead, it downloads all the dependencies and builds them into a container.
   - The initial build for Flatpak may take longer, as it needs to build all the required dependencies.

> Common dev tasks (environment setup, running, testing, linting, building, translations, and Flatpak) are wrapped in the top-level `Makefile`. Run `make help` for the list.

## CachyOS / Arch Linux native setup

The native build is a good first choice when troubleshooting video acceleration because it uses the host Mesa/VA-API stack. Hidamari embeds LibVLC through X11, so a Wayland desktop needs XWayland enabled. Vulkan packages are not a dependency.

Install the build/runtime libraries (the application itself is installed through the AUR package or the checkout below):

```bash
sudo pacman -S --needed base-devel git meson ninja pkgconf uv \
  gtk3 python-gobject libappindicator-gtk3 libwnck3 gnome-desktop-4 \
  webkit2gtk-4.1 vlc ffmpeg xdg-user-dirs desktop-file-utils
```

For a checkout-based development run:

```bash
PYTHONPATH=src python3 -m hidamari --diagnostics
make sync
make run
```

`make sync` creates a `uv` environment which reuses system PyGObject. `make run` installs into `~/.local` and runs Hidamari through that environment. For normal desktop use, the AUR package or Flatpak is simpler than launching the installed script outside the `uv` environment.

### Radeon HD 8650G / VA-API

The HD 8650G is an older AMD APU. It does not need Vulkan for Hidamari. If the kernel/Mesa stack exposes VA-API decode for the card, VLC can use it; the app otherwise keeps VLC's automatic/software decoding path. Install Mesa's VA-API driver and the `vainfo` utility, then inspect the available H.264 profiles:

```bash
sudo pacman -S --needed mesa libva libva-mesa-driver libva-utils
ls -l /dev/dri/renderD*
vainfo --display drm --device /dev/dri/renderD128
hidamari --diagnostics
```

Use the render node shown by `ls` in the `vainfo` command if it is not `renderD128`. Successful H.264 `VAEntrypointVLD` profiles indicate a hardware decode path. If the probe fails, do not force a different kernel driver blindly; playback still works through VLC's software path, but choose H.264/AVC and modest source files for lower CPU use. These environment overrides must be set before Hidamari starts; quit an already-running Hidamari instance first. Run one of these commands at a time to compare VA-API, software, and lower stream-resolution behavior:

```bash
HIDAMARI_HWACCEL=vaapi hidamari -d
HIDAMARI_HWACCEL=software hidamari -d
HIDAMARI_STREAM_MAX_HEIGHT=720 hidamari
```

`HIDAMARI_HWACCEL` accepts `auto` (default), `vaapi`, `vdpau`, or `software`. Use `auto` unless `vainfo` confirms a working driver. The stream height setting limits streaming formats only; it does not transcode local files. For this generation of APU, H.264/AVC at 720p/30 fps is a sensible low-load starting point. VLC uses the PulseAudio protocol for audio; CachyOS PipeWire setups normally provide it through `pipewire-pulse`. Webpage wallpapers can be substantially heavier than video playback.

## Build and Install
### Dependencies
#### PyGObject
Please refer to the [official documentation](https://pygobject.readthedocs.io/en/latest/getting_started.html#gettingstarted). The system-provided PyGObject is recommended.

#### Python packages
- Installing with [uv](https://docs.astral.sh/uv/) (recommended)

  The dev environment is defined in `pyproject.toml`. Set it up, then build/install and run via the Makefile:
```bash
make sync   # uv venv --system-site-packages && uv sync
make run    # meson install into ~/.local, then run it (through the uv env)
```
  `make sync` uses `--system-site-packages` so the system-provided PyGObject (`gi`) resolves.
  `make run` installs into `~/.local` (no sudo) and runs the installed app so it loads
  its compiled resources (UI + icons) — re-run it after changing Python code. Override
  the location with `make install PREFIX=/some/prefix`.

- Installing with pip (without uv)
```bash
pip install pillow pydbus python-vlc "yt-dlp[default]" requests setproctitle
```

- Installing from system-provided packages (Fedora):
```bash
sudo dnf install python3-pillow python3-pydbus python3-requests python3-setproctitle python3-vlc yt-dlp
```

> `pyproject.toml` is the single source of truth for the Python dependencies.
> The Flatpak build derives its `pypi-deps.json` from it via `make pypi-deps`
> (which runs `pkgs/flatpak/generate-pypi-deps.sh`).

#### Linting and formatting
[Ruff](https://docs.astral.sh/ruff/) handles both linting and formatting (configured in `pyproject.toml`):
```bash
make lint     # ruff check
make format   # ruff format
```

#### Runtime dependencies
Note 1: Packages may have different names among distros. Hint: [pkgs.org](https://pkgs.org/) is very convenient to search packages for your distro.

Note 2: Please don't worry about the `gnome-desktop` package; it's just a library, not the GNOME Desktop Environment.

- Ubuntu:
```bash
sudo apt install dconf-cli libappindicator3-1 libgnome-desktop-4-1 libwebkit2gtk-4.1-0 libwnck-3-0 mesa-utils vdpauinfo xdg-user-dirs
```

- Fedora:
```bash
sudo dnf install dconf glx-utils gnome-desktop4 libappindicator-gtk3 libwnck3 vdpauinfo webkit2gtk4.1 xdg-user-dirs
```

#### Build dependencies
- Ubuntu:
```bash
sudo apt install git meson gtk-update-icon-cache desktop-file-utils
```

- Fedora:
```bash
sudo dnf install git meson gtk-update-icon-cache desktop-file-utils
```

### Install
`make install` installs into `~/.local` (no sudo). For a system-wide install, pass a prefix:
```bash
make install                      # ~/.local
sudo make install PREFIX=/usr/local
```

### Uninstall
```bash
make uninstall
```
This removes exactly what `make install` installed (from the same `PREFIX`).

## Build as Flatpak
First, please make sure you have `flatpak` and `flatpak-builder` installed on your system. For more details, please refer to the [Flatpak official documentation](https://docs.flatpak.org/en/latest/first-build.html).

All Flatpak packaging files live under [`pkgs/flatpak`](../pkgs/flatpak/), including the manifest `io.github.jeffshee.Hidamari.json`, the bundled build modules (`vlc.json`, `pypi-deps.json`), VLC patches (`libvlc/`), and the `shared-modules` submodule.

### Environment Setup
For Flatpak development, VSCode with the Flatpak extension (`bilelmoussaoui.flatpak-vscode`) is recommended. Alternatively, GNOME Builder is also useful when building Flatpak applications.

When cloning the Hidamari repo, you should also pull the submodules (`shared-modules`), as they are required for building the Flatpak.

To do so, use `--recurse-submodules` when cloning:
```bash
git clone --recurse-submodules https://github.com/jeffshee/hidamari.git
```
Alternatively, if you've already cloned the repo, use the following command:
```bash
git submodule update --init --recursive
```
### Build and Run
With the extension installed, press <kbd>F1</kbd> (command palette), search for "flatpak", and run the desired action.

![](vscode-flatpak.png)

Alternatively, build and install it from the command line (run from the repository root):
```bash
make flatpak
```
