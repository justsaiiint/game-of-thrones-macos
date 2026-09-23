# Development

```sh
python3 -m unittest discover -s tests -v
```

`prepare --root /path/to/new/folder --app /path/to/new.app` creates a separate test setup. Pass the same `--root` to later commands. `--cache` can reuse downloaded archives, with checksum verification.

## Working route

The Windows game is a 32-bit Direct3D 9 application. The tested stack is Wine Sikarugir 11.0 revision 1, D9VK 1.10.3-async, Mesa KosmicKrisp (reported driver version 26.2.99), and Vulkan loader 1.4.350.

The game receives `CX_LIBVULKAN`, `VK_DRIVER_FILES`, and `VK_ICD_FILENAMES` pointing to the selected loader and driver. Its local native `d3d9.dll` is loaded with `WINEDLLOVERRIDES=d3d9=n,b;gameoverlayrenderer=d;winemenubuilder.exe=d`. `SteamAppId` and `SteamGameId` are 330840. D9VK caps rendering at 60 FPS. Game preferences and saves are not copied or edited by this repository.

The native DLL comes from `Template-1.0.18.app/Contents/Frameworks/renderer/d9vk/wine/i386-windows/d3d9.dll`. Its Wine builtin marker is cleared so Wine loads the game-local copy. The expected source and result hashes are checked in `native_d3d9`.

Steam uses `-no-cef-sandbox` and `-cef-disable-gpu`. The former disables its Chromium sandbox inside Wine. This Wine prefix separates configuration and saves, but is not a security sandbox.

## Validation scope

The original shared-Steam setup was played on one M4 Pro MacBook Pro, 24 GB RAM, macOS 27.0. The user reported fullscreen picture, audio, controls, and around 60 FPS at 2560 × 1440. This is a gameplay report, not a benchmark or a completed playthrough.

Fresh preparation from the pinned archives passed on that Mac. The prepared D9VK DLL and KosmicKrisp driver matched the working installation byte for byte. The isolated Windows process query, document-folder separation, and 14 automated checks passed. The current Valve installer also matched the pinned checksum.

A complete new Steam sign-in, game download, and gameplay run through this packaged installer have not been tested. No second-machine validation is claimed.

Keep download hashes pinned. If an upstream download changes, review it before updating the manifest. Review logs for account or path information before sharing them.
