# Third-party components

The setup downloads the upstream archives pinned in [dependencies.json](dependencies.json). This repository distributes only scripts and documentation under MIT, not the dependencies themselves.

| Component | Source | License |
| --- | --- | --- |
| Wine Sikarugir 11.0 revision 1 | [Engine release](https://github.com/Sikarugir-App/Engines/releases/tag/v1.0), [downstream source](https://github.com/Sikarugir-App/wine) | Wine is [LGPL-2.1-or-later](https://github.com/wine-mirror/wine/blob/wine-11.0/LICENSE). |
| D9VK 1.10.3-async | [Sikarugir D9VK](https://github.com/Sikarugir-App/d9vk), packaged in [Template 1.0.18](https://github.com/Sikarugir-App/Template/releases/tag/v1.0) | [zlib/libpng](https://github.com/Sikarugir-App/d9vk/blob/master/LICENSE). |
| Mesa KosmicKrisp | [Driver documentation](https://docs.mesa3d.org/drivers/kosmickrisp.html), packaged in Template 1.0.18 | Most Mesa code is MIT, with [per-component exceptions](https://docs.mesa3d.org/license.html). |
| Vulkan loader 1.4.350 | [Vulkan Loader](https://github.com/KhronosGroup/Vulkan-Loader), packaged in Template 1.0.18 | Primarily Apache-2.0, with [exceptions](https://github.com/KhronosGroup/Vulkan-Loader/blob/main/LICENSE.txt). |
| DXMT | [Upstream source](https://github.com/3Shain/dxmt/tree/7c8dee1c2d73415301ceb7d1fa810861cef4cd67), packaged in Template 1.0.18 | [LGPL-2.1-or-later](https://github.com/3Shain/dxmt/blob/7c8dee1c2d73415301ceb7d1fa810861cef4cd67/LICENSE). |
| GStreamer and dependency libraries | Template 1.0.18 Frameworks | Separately licensed. See [GStreamer's licensing FAQ](https://gstreamer.freedesktop.org/documentation/frequently-asked-questions/licensing.html). |
| Windows Steam | [Valve's installer](https://cdn.akamai.steamstatic.com/client/installer/SteamSetup.exe) | Proprietary. |
| Game of Thrones | The user's Steam library | Proprietary. Ownership is required. |

Extraction selects the Template archive's top-level dependency dylibs, GStreamer, DXMT, and the 32-bit D9VK DLL with its license/version files. It excludes the Sikarugir launcher/SDK and Apple's D3DMetal renderer. DXMT supplies the existing Wine environment's DirectX 11 path. The game itself uses D9VK and KosmicKrisp.

The installer clears the 16-byte Wine builtin marker at file offsets 64-79 in a local copy of the pinned D9VK DLL. It verifies the original and resulting hashes. Executable code is unchanged. The upstream DLL and its license remain in the runtime folder.

Exact source/build correspondence for these repacked binaries has not been established. Linked source projects describe their lineage, not a reproducible build guarantee. Anyone redistributing runtime binaries must separately verify corresponding source, notices, and redistribution requirements.

Installer helpers are adapted from [sifu-macos](https://github.com/justsaiiint/sifu-macos) and [outer-wilds-macos](https://github.com/justsaiiint/outer-wilds-macos). Their MIT notices are retained in [LICENSE](LICENSE).
