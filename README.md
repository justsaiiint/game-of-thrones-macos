# Game of Thrones on macOS

Run the Windows Steam edition of **Game of Thrones - A Telltale Games Series (2014)** on an Apple Silicon Mac, using Wine, D9VK, and Mesa KosmicKrisp.

Tested on one M4 Pro MacBook Pro with 24 GB RAM and macOS 27.0, with fullscreen gameplay, sound, controls, and around 60 FPS. Other Macs are untested.

## Requirements

- Apple Silicon Mac with macOS 26 or later and Rosetta 2
- Python 3.9 or later
- Your own Steam copy of the game, already in your library
- Enough free space for Steam, the game, and about 3 GB of setup files

## Install

Download this repository, open Terminal in its folder, and run:

```sh
python3 thronesmac.py prepare
python3 thronesmac.py install-steam
```

Complete the Windows Steam installer, sign in, and install the game into its default library. This creates a separate Windows environment and leaves existing Steam installations alone.

Setup enables a brief check every 30 seconds that removes abandoned Wine device helpers after their environment exits. Active Steam sessions and games are protected.

## Update an existing installation

Download the latest repository, then run `python3 thronesmac.py cleanup-enable`. For a custom installation, add `--root /path/to/installation`. This leaves game files, saves, and settings unchanged.

## Play

Open **Game of Thrones macOS.app** in your user Applications folder (`~/Applications`). Use this app to apply the game's renderer. You can drag it to the Dock.

In the game, open **Settings → Graphics**, enable fullscreen, and choose your resolution. Quit through the game menu to save your settings. The launcher caps rendering at 60 FPS.

## Help

Run `python3 thronesmac.py steam` to open its Windows Steam, or `python3 thronesmac.py doctor` to check the installation.

Files live in `~/Library/Application Support/Game of Thrones macOS`. Saves stay inside its `prefix/drive_c/users/<user>/Documents/Telltale Games` folder. To uninstall, quit the game and its Windows Steam, back up that folder, run `python3 thronesmac.py cleanup-disable` (with the same `--root` if customized), then move the app and installation folder to Trash.

## Credits

[MIT](LICENSE) for the setup scripts and documentation. Dependencies retain their [own licenses](THIRD_PARTY.md). No game files, saves, Steam accounts, or runtime binaries are included.

Unofficial community setup, not affiliated with Telltale, HBO, or Valve. See [development notes](DEVELOPMENT.md) for the implementation and validation scope.
