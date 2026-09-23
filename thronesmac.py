#!/usr/bin/env python3
"""Run the Windows Steam edition of Telltale Game of Thrones on Apple Silicon."""

import argparse
import contextlib
import csv
import time
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request


VERSION = "0.1.0"
DEFAULT_ROOT = Path.home() / "Library/Application Support/Game of Thrones macOS"
DEFAULT_APP = Path.home() / "Applications/Game of Thrones macOS.app"
MARKER = "game-of-thrones-macos.json"
STEAM = r"C:\Program Files (x86)\Steam\Steam.exe"
APP_ID = "330840"


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".thronesmac-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            output.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_json(path, data):
    atomic_write(path, json.dumps(data, indent=2) + "\n")


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def download(entry, cache):
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / entry["filename"]
    if destination.exists():
        if digest(destination) != entry["sha256"]:
            raise RuntimeError(f"Checksum mismatch: {destination}. Move it aside and retry.")
        return destination
    fd, partial = tempfile.mkstemp(prefix=destination.name + ".", dir=cache)
    try:
        print(f"Downloading {entry['filename']}...", flush=True)
        request = urllib.request.Request(entry["url"], headers={"User-Agent": "game-of-thrones-macos/" + VERSION})
        with os.fdopen(fd, "wb") as output, urllib.request.urlopen(request, timeout=60) as response:
            if not response.url.startswith("https://"):
                raise RuntimeError("Refusing a non-HTTPS redirect")
            shutil.copyfileobj(response, output)
        if digest(partial) != entry["sha256"]:
            raise RuntimeError("Download checksum changed. Nothing will run. Review the upstream release before updating the manifest.")
        os.replace(partial, destination)
    finally:
        if os.path.exists(partial):
            os.unlink(partial)
    return destination


def inside(path, root):
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def extract_selected(archive, destination, select):
    """Extract only mapped members, refusing traversal, special files, and hard links."""
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:xz") as bundle:
        for member in bundle:
            relative = select(member.name)
            if relative is None:
                continue
            relative = PurePosixPath(relative)
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError("Unsafe archive path")
            target = destination / str(relative)
            if not inside(target, destination):
                raise RuntimeError("Archive path escapes destination")
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.isdir():
                target.mkdir(exist_ok=True)
            elif member.issym():
                link = Path(member.linkname)
                if link.is_absolute() or not inside(target.parent / link, destination):
                    raise RuntimeError("Unsafe archive symlink")
                target.symlink_to(member.linkname)
            elif member.isfile():
                if target.is_symlink():
                    raise RuntimeError("Refusing to write through a symlink")
                with bundle.extractfile(member) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
                target.chmod(member.mode & 0o777)
            else:
                raise RuntimeError("Unsupported archive member type")


def wine_member(name):
    prefix = "wswine.bundle/"
    return "Wine.app/Contents/" + name[len(prefix):] if name.startswith(prefix) else None


def template_member(name):
    prefix = "Template-1.0.18.app/Contents/Frameworks/"
    if not name.startswith(prefix):
        return None
    relative = name[len(prefix):]
    if relative in ("renderer/d9vk/LICENSE", "renderer/d9vk/version", "renderer/d9vk/wine/i386-windows/d3d9.dll"):
        return "d9vk/" + relative[len("renderer/d9vk/"):]
    if relative.startswith("renderer/dxmt/"):
        return "dxmt/" + relative[len("renderer/dxmt/"):]
    if relative == "GStreamer.framework" or relative.startswith("GStreamer.framework/"):
        return "Frameworks/" + relative
    if "/" not in relative and relative.endswith(".dylib"):
        return "Frameworks/" + relative
    return None


def wine_env(root, game=False):
    contents = root / "runtime/Wine.app/Contents"
    frameworks = root / "runtime/Frameworks"
    env = os.environ.copy()
    # A caller's Wine/DXMT overrides must not select another prefix or renderer.
    for key in list(env):
        if key.startswith(("WINE", "DXMT_", "DXVK_", "GST_", "DYLD_", "VK_", "MVK_", "CX_", "SteamAppId", "SteamGameId", "Sikarugir")):
            del env[key]
    env.update({
        "WINEPREFIX": str(root / "prefix"),
        "WINELOADER": str(contents / "bin/wine"),
        "WINESERVER": str(contents / "bin/wineserver"),
        "SikarugirAppWine11": "1",
        "WINEDLLPATH_DXMT": str(root / "runtime/dxmt/wine"),
        "WINEDLLPATH_PREPEND": str(root / "runtime/dxmt/wine"),
        "WINEDLLOVERRIDES": "winemenubuilder.exe=d",
        "WINEDEBUG": "-all",
        "DYLD_FALLBACK_LIBRARY_PATH": f"{frameworks}:{frameworks}/GStreamer.framework/Versions/1.0/lib:/usr/lib",
        "GST_PLUGIN_SYSTEM_PATH_1_0": f"{frameworks}/GStreamer.framework/Versions/1.0/lib/gstreamer-1.0",
        "GST_PLUGIN_SCANNER_1_0": f"{frameworks}/GStreamer.framework/Versions/1.0/libexec/gstreamer-1.0/gst-plugin-scanner",
        "GST_REGISTRY": str(root / "prefix/gstreamer-registry.bin"),
        "DXMT_CONFIG_FILE": "Z:" + str(root / "dxmt.conf"),
        "DXMT_LOG_PATH": "Z:" + str(root / "logs"),
        "PATH": str(contents / "bin") + ":" + env.get("PATH", "/usr/bin:/bin"),
    })
    if game:
        env.update({
            "CX_LIBVULKAN": str(frameworks / "libvulkan.1.4.350.dylib"),
            "VK_DRIVER_FILES": str(root / "runtime/game-of-thrones/KosmicKrisp_icd.json"),
            "VK_ICD_FILENAMES": str(root / "runtime/game-of-thrones/KosmicKrisp_icd.json"),
            "WINEDLLOVERRIDES": "d3d9=n,b;gameoverlayrenderer=d;winemenubuilder.exe=d",
            "DXVK_CONFIG_FILE": "Z:" + str(root / "runtime/game-of-thrones/dxvk.conf"),
            "DXVK_LOG_PATH": str(root / "logs"),
            "DXVK_STATE_CACHE_PATH": str(root / "prefix"),
            "SteamAppId": APP_ID, "SteamGameId": APP_ID,
        })
    return env


def wine(root, args, wait=True, timeout=120, game=False, cwd=None):
    env = wine_env(root, game)
    with (root / "logs/runtime.log").open("ab") as log:
        command = [env["WINELOADER"], *args]
        if wait:
            return subprocess.run(command, env=env, cwd=cwd, stdout=log, stderr=log, check=True, timeout=timeout)
        return subprocess.Popen(command, env=env, cwd=cwd, stdout=log, stderr=log, start_new_session=True)


def require_install(root):
    marker = root / MARKER
    if not marker.is_file() or json.loads(marker.read_text()).get("project") != "game-of-thrones-macos":
        raise RuntimeError("This directory is not a game-of-thrones-macos installation")
    return json.loads(marker.read_text())


@contextlib.contextmanager
def locked(root):
    import fcntl
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".settings.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another installer or launcher operation is in progress")
        yield


def create_app(root, app):
    if app.exists():
        raise RuntimeError(f"Refusing to replace an existing app: {app}")
    contents = app / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    info = {"CFBundleExecutable": "Launch", "CFBundleIdentifier": "io.github.game-of-thrones-macos.launcher",
            "CFBundleName": "Game of Thrones macOS", "CFBundleDisplayName": "Game of Thrones macOS",
            "CFBundlePackageType": "APPL", "CFBundleVersion": VERSION,
            "CFBundleShortVersionString": VERSION, "NSHighResolutionCapable": True}
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    launcher = contents / "MacOS/Launch"
    command = [str(root / "launcher/thronesmac.py"), "launch", "--root", str(root)]
    candidates = list(dict.fromkeys([sys.executable, "/opt/homebrew/bin/python3", "/usr/local/bin/python3", "/usr/bin/python3"]))
    script = "#!/bin/bash\nset -euo pipefail\nexec >> " + shlex.quote(str(root / "logs/launcher.log")) + " 2>&1\n"
    script += "for candidate in " + shlex.join(candidates) + "; do\n"
    script += '  if [[ -x "$candidate" ]] && "$candidate" -c "import sys; sys.exit(sys.version_info < (3, 9))"; then\n'
    script += '    exec "$candidate" ' + shlex.join(command) + "\n  fi\ndone\n"
    script += "echo 'Python 3.9 or later is required. Restore Python, then open this app again.' >&2\nexit 1\n"
    launcher.write_text(script)
    launcher.chmod(0o755)


def check_host():
    if platform.system() != "Darwin":
        raise RuntimeError("This installer requires macOS")
    version = platform.mac_ver()[0]
    if not version or int(version.split(".")[0]) < 26:
        raise RuntimeError("KosmicKrisp requires macOS 26 or later")
    arm = subprocess.run(["/usr/sbin/sysctl", "-n", "hw.optional.arm64"], capture_output=True, text=True)
    if arm.stdout.strip() != "1":
        raise RuntimeError("This release targets Apple Silicon Macs only")
    if subprocess.run(["/usr/bin/arch", "-x86_64", "/usr/bin/true"], capture_output=True).returncode:
        raise RuntimeError("Rosetta 2 is required. Install it through Apple's prompt, then retry.")


SOURCE_DLL_HASH = "669bacd131c5fd47a8dbaf4a2881493853e99b2b16a3998cc220228ead4d1e1c"
NATIVE_DLL_HASH = "379500d9a4fde64bd4b452b885354778a538a15e9dbdbdf2d7561fc0c1e4dbb2"
GAME_RELATIVE = "prefix/drive_c/Program Files (x86)/Steam/steamapps/common/Game of Thrones"
GAME_EXE = r"C:\Program Files (x86)\Steam\steamapps\common\Game of Thrones\Thrones.exe"


def native_d3d9(source, destination):
    """Clear only the Wine builtin marker in the pinned DLL's DOS stub."""
    if digest(source) != SOURCE_DLL_HASH:
        raise RuntimeError("Unexpected D9VK binary. Refusing to modify it.")
    data = bytearray(source.read_bytes())
    if data[64:80] != b"Wine builtin DLL":
        raise RuntimeError("Expected Wine builtin marker is missing")
    data[64:80] = bytes(16)
    if hashlib.sha256(data).hexdigest() != NATIVE_DLL_HASH:
        raise RuntimeError("Patched D9VK checksum mismatch")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)


def isolate_documents(root):
    """Wine maps Documents to macOS by default. Keep this game's saves local."""
    users = root / "prefix/drive_c/users"
    for user in users.iterdir():
        if not user.is_dir() or user.is_symlink():
            continue
        for name in ("Documents", "My Documents"):
            documents = user / name
            if documents.is_symlink():
                documents.unlink()  # Remove the link, never its target or contents.
            documents.mkdir(exist_ok=True)


def register_game(root):
    # Direct launch bypasses Steam's first-run installscript. These are its
    # installation identifiers, not preferences or player progress.
    registration = root / "game.reg"
    atomic_write(registration, 'REGEDIT4\n\n'
        '[HKEY_CURRENT_USER\\Software\\Telltale Games\\Thrones.exe]\n'
        '"Distribution"="Steam"\n'
        '"Franchise"="GameOfThrones100"\n'
        '"SaveGameFolderName"="Game of Thrones"\n'
        '"Install Location"="C:\\\\Program Files (x86)\\\\Steam\\\\steamapps\\\\common\\\\Game of Thrones\\\\"\n')
    wine(root, ["regedit", "/S", str(registration)])


def install_game_renderer(root):
    game = root / GAME_RELATIVE
    if not inside(game, root):
        raise RuntimeError("Game must be inside this installation's Steam library")
    if not (game / "Thrones.exe").is_file():
        raise RuntimeError("Install Game of Thrones in this Windows Steam's default library first")
    target = game / "d3d9.dll"
    if target.is_symlink():
        raise RuntimeError("Refusing to replace a linked d3d9.dll")
    if target.exists():
        if digest(target) != NATIVE_DLL_HASH:
            raise RuntimeError("The game already has a different d3d9.dll. Move it aside before using this launcher.")
        return
    source = root / "runtime/game-of-thrones/d3d9.dll"
    if digest(source) != NATIVE_DLL_HASH:
        raise RuntimeError("Installed D9VK checksum mismatch")
    shutil.copy2(source, target)


def process_names(root):
    env = wine_env(root)
    result = subprocess.run([env["WINELOADER"], "tasklist", "/FO", "CSV", "/NH"],
                            env=env, capture_output=True, text=True, check=True, timeout=30)
    return {row[0].lower() for row in csv.reader(result.stdout.splitlines()) if row}


def start_steam(root, wait_for_login=False):
    if not (root / "prefix/drive_c/Program Files (x86)/Steam/Steam.exe").is_file():
        raise RuntimeError("Install Windows Steam first with install-steam")
    connection = root / "prefix/drive_c/Program Files (x86)/Steam/logs/connection_log.txt"
    offset = connection.stat().st_size if connection.exists() else 0
    wine(root, [STEAM, "-no-cef-sandbox", "-cef-disable-gpu", "steam://open/library"], wait=False)
    if not wait_for_login:
        return True
    print("Waiting for Steam to sign in...", flush=True)
    for _ in range(120):
        if connection.exists():
            if connection.stat().st_size < offset:
                offset = 0
            with connection.open("rb") as log:
                log.seek(offset)
                if b"RecvMsgClientLogOnResponse() : processing complete" in log.read():
                    return True
        time.sleep(1)
    print("Finish signing in to Windows Steam, then open the game launcher again.")
    return False


def prepare(args):
    check_host()
    root, app = args.root, args.app
    if root.exists() or app.exists():
        raise RuntimeError("Refusing to replace an existing installation or app. Choose a new --root and --app.")
    manifest = json.loads(Path(__file__).with_name("dependencies.json").read_text())
    files = {key: download(value, args.cache) for key, value in manifest.items()}
    with locked(root):
        for name in ["logs", "downloads", "launcher"]:
            (root / name).mkdir(exist_ok=True)
        print("Extracting the pinned runtime...", flush=True)
        extract_selected(files["wine"], root / "runtime", wine_member)
        extract_selected(files["template"], root / "runtime", template_member)
        contents = root / "runtime/Wine.app/Contents"
        (contents / "MacOS").mkdir(exist_ok=True)
        (contents / "MacOS/wine").symlink_to("../bin/wine")
        info = {"CFBundleExecutable": "wine", "CFBundleIdentifier": "org.winehq.wine",
                "CFBundleName": "Game of Thrones Runtime", "CFBundleDisplayName": "Game of Thrones Runtime",
                "CFBundlePackageType": "APPL", "CFBundleVersion": "11.0.1",
                "CFBundleShortVersionString": "11.0.1", "NSHighResolutionCapable": True,
                "NSPrincipalClass": "NSApplication"}
        (contents / "Info.plist").write_bytes(plistlib.dumps(info))
        renderer = root / "runtime/game-of-thrones"
        native_d3d9(root / "runtime/d9vk/wine/i386-windows/d3d9.dll", renderer / "d3d9.dll")
        write_json(renderer / "KosmicKrisp_icd.json", {
            "file_format_version": "1.0.0", "ICD": {
                "library_path": str(root / "runtime/Frameworks/libvulkan_kosmickrisp.dylib"),
                "api_version": "1.3.0"}})
        atomic_write(renderer / "dxvk.conf", "d3d9.maxFrameRate = 60\n")
        atomic_write(root / "dxmt.conf", "")
        shutil.copy2(files["steam"], root / "downloads/SteamSetup.exe")
        for name in ["thronesmac.py", "dependencies.json"]:
            shutil.copy2(Path(__file__).with_name(name), root / "launcher" / name)
        print("Creating the Windows environment...", flush=True)
        wine(root, ["wineboot", "--init"])
        register_game(root)
        isolate_documents(root)
        write_json(root / MARKER, {"project": "game-of-thrones-macos", "version": VERSION,
                                  "app": str(app), "dependencies": manifest})
        create_app(root, app)
    print(f"Prepared: {root}\nLauncher: {app}\nNext: python3 thronesmac.py install-steam --root {shlex.quote(str(root))}")


def main(argv=None):
    if sys.version_info < (3, 9):
        raise RuntimeError("Python 3.9 or later is required")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ["prepare", "install-steam", "steam", "launch", "doctor"]:
        item = sub.add_parser(command)
        item.add_argument("--root", type=lambda p: Path(p).expanduser().resolve(), default=DEFAULT_ROOT)
        if command == "prepare":
            item.add_argument("--cache", type=lambda p: Path(p).expanduser().resolve(),
                              default=Path.home() / "Library/Caches/game-of-thrones-macos")
            item.add_argument("--app", type=lambda p: Path(p).expanduser().resolve(), default=DEFAULT_APP)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        prepare(args)
        return
    root = args.root
    config = require_install(root)
    if not inside(root / "logs", root):
        raise RuntimeError("Log files must stay inside the installation")
    if args.command == "doctor":
        print(json.dumps({"version": config["version"], "fps_cap": 60,
            "steam_installed": (root / "prefix/drive_c/Program Files (x86)/Steam/Steam.exe").is_file(),
            "game_installed": (root / GAME_RELATIVE / "Thrones.exe").is_file(),
            "renderer_valid": (root / "runtime/game-of-thrones/d3d9.dll").is_file() and
                              digest(root / "runtime/game-of-thrones/d3d9.dll") == NATIVE_DLL_HASH,
            "kosmickrisp_installed": (root / "runtime/Frameworks/libvulkan_kosmickrisp.dylib").is_file()}, indent=2))
        return
    check_host()
    with locked(root):
        if args.command == "install-steam":
            if (root / "prefix/drive_c/Program Files (x86)/Steam/Steam.exe").exists():
                raise RuntimeError("Steam is already installed. Use the steam command.")
            wine(root, [str(root / "downloads/SteamSetup.exe")], wait=False)
            print("Complete the Windows Steam installer and sign in yourself.")
        elif args.command == "steam":
            start_steam(root)
        else:
            processes = process_names(root)
            if "thrones.exe" in processes:
                print("Game of Thrones is already running.")
                return
            install_game_renderer(root)
            if "steam.exe" not in processes and not start_steam(root, wait_for_login=True):
                return
            wine(root, [GAME_EXE], wait=False, game=True, cwd=root / GAME_RELATIVE)
            print("Game of Thrones is starting.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError, tarfile.TarError) as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)
