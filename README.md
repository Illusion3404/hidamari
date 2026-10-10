<p align="center"><img src="https://raw.githubusercontent.com/jeffshee/hidamari/master/res/hidamari.svg" width="256"></p>

<p align="center">Video wallpaper for Linux. Written in Python. 🐍</p>  
<p align="center">Hidamari 日溜まり【ひだまり】(n) sunny spot; exposure to the sun</p>

# Hidamari　ーひだまりー
If you like my project, please consider buying me a coffee!! (⁎˃ ꇴ ˂⁎)ｯ

[![Github-sponsors](https://img.shields.io/badge/sponsor-30363D?style=for-the-badge&logo=GitHub-Sponsors&logoColor=#EA4AAA)](https://github.com/sponsors/jeffshee)
[![Ko-Fi](https://img.shields.io/badge/Ko--fi-F16061?style=for-the-badge&logo=ko-fi&logoColor=white)](https://ko-fi.com/jeffshee)
[![BuyMeACoffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/jeffshee)

Also please don't forget to click that star button! 🌟  
Your support is truly appreciated!

## Join our Discord!

[![Discord](https://img.shields.io/badge/Discord-%235865F2.svg?style=for-the-badge&logo=discord&logoColor=white)](https://discord.gg/mP7yg4gX7g)

## For GNOME user 🐾
Please also check my new project [Hanabi](https://github.com/jeffshee/gnome-ext-hanabi)! While the project is still in its infancy, it has the potential to become more integrated with GNOME Shell

## Features 🔥

There are several solutions to achieve video as wallpaper on Linux, for example:

1. [Xwinwrap + mpv](https://www.linuxuprising.com/2019/05/livestream-wallpaper-for-your-gnome.html)
2. [Komorebi](https://github.com/cheesecakeufo/komorebi)

Hidamari offers similar feature as above, with additional features listed below:

- [x] Autostart after login
- [x] Apply static wallpaper with blur effect <sup>1</sup>
- [x] Detect maximized window and fullscreen mode <sup>2</sup>
- [x] Volume control
- [x] Mute/Pause the playback anytime with just 2 clicks!
- [x] I'm feeling lucky <sup>3</sup>
- [x] Hardware accelerated video decoding! <sup>4</sup>
- [x] Gnome Wayland support!
- [x] Multi-monitor support!
- [x] Streaming URL support! <sup>5</sup>
- [x] Webpage as wallpaper! <sup>6</sup>
- [ ] You name it! =)

<sup>1</sup> Video frame can be applied as system wallpaper, look great in <i>GNOME</i> (currently GNOME exclusive, support for other DE might be added if requested...)  
<sup>2</sup> Automatically pauses playback when maximized window or full screen mode is detected (currently X11 only...)  
<sup>3</sup> Randomly select and play a video  
<sup>4</sup> Uses <i>vlc</i>; hardware decoding is optional and depends on the installed VA-API/VDPAU driver. Vulkan is not required.
<sup>5</sup> Use <i>yt-dlp</i> as backend, tested with YouTube videos  
<sup>6</sup> Theoretically it can be anything from a normal webpage to <i>Unity/Godot WebGL games</i>, be creative!

> **Wayland note:** LibVLC is embedded through its X11 window API, so Hidamari uses XWayland in a Wayland session. XWayland must be installed/enabled; maximized-window detection remains X11-only. Hidamari does not require Vulkan.

## Installation ⏬
### Flatpak 📦
It is available on Flathub!

<a href='https://flathub.org/apps/details/io.github.jeffshee.Hidamari'><img width='240' alt='Download Hidamari on Flathub' src='https://flathub.org/assets/badges/flathub-badge-en.png'/></a>

#### Command line instructions
Install:  
Make sure to follow the [setup guide](https://flatpak.org/setup/) before installing
```
flatpak install flathub io.github.jeffshee.Hidamari
```
Run:  
```
flatpak run io.github.jeffshee.Hidamari
```

### Unofficial package
These are maintained by the community!
| Distro     | URL                                     | Maintainer                            |
|------------|-----------------------------------------|---------------------------------------|
| Arch Linux | [![AUR](https://img.shields.io/aur/version/hidamari?style=for-the-badge)](https://aur.archlinux.org/packages/hidamari) | None |

### CachyOS / Arch Linux graphics notes

Hidamari runs on Arch-based systems and does **not** need Vulkan. For an AMD APU such as the Radeon HD 8650G, VLC can use Mesa VA-API for supported codecs (notably H.264) when the legacy GPU driver exposes those decode profiles. The application falls back to VLC's normal decoder selection if acceleration is unavailable.

On CachyOS, install the native AUR package (`yay -S hidamari` or your preferred AUR helper), or follow the [native build and VA-API setup guide](docs/dev.md#cachyos--arch-linux-native-setup). In a Wayland session, make sure XWayland is enabled.

For older/low-power hardware, try selecting **H.264/AVC**, 720p, and 30 fps videos. For streams, Hidamari prefers H.264 and avoids choosing a resolution above the display. To further limit stream resolution, quit Hidamari and start it with:

```bash
HIDAMARI_STREAM_MAX_HEIGHT=720 hidamari
```

To inspect the graphics stack without starting the GUI, run:

```bash
hidamari --diagnostics
```

`--diagnostics` reports the detected Linux session, DRM render devices, VA-API decode profiles, and VLC libraries.

## Screenshot 📸

![](https://raw.githubusercontent.com/jeffshee/hidamari/master/res/screenshot-1.png)
![](https://raw.githubusercontent.com/jeffshee/hidamari/master/res/screenshot-2.png)
![](https://raw.githubusercontent.com/jeffshee/hidamari/master/res/screenshot-3.png)

## Please!! 🙏

Collaboration is welcome! Let's make it better together~  
Feel free to open an issue if you have any problem or suggestion 🤗  

## Contributors ✨

<a href="https://github.com/jeffshee/hidamari/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=jeffshee/hidamari" />
</a>

Made with [contributors-img](https://contrib.rocks).  
Icons made by [Freepik](http://www.freepik.com/) from [Flaticon](https://www.flaticon.com)
