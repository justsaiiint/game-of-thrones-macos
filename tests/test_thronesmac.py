import io
import json
from pathlib import Path
import sys
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import thronesmac


class ArchiveTests(unittest.TestCase):
    def test_selection_excludes_proprietary_renderer_and_wrapper(self):
        base = 'Template-1.0.18.app/Contents/Frameworks/'
        for name in ['renderer/d3dmetal/foo', 'SikarugirSdk.framework/binary', '../secret']:
            self.assertIsNone(thronesmac.template_member(base + name))
        self.assertEqual(thronesmac.template_member(base + 'renderer/dxmt/LICENSE'), 'dxmt/LICENSE')
        self.assertEqual(thronesmac.template_member(base + 'libtest.dylib'), 'Frameworks/libtest.dylib')

    def test_traversal_and_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for label, info in [('traversal', tarfile.TarInfo('../escape')), ('symlink', tarfile.TarInfo('link'))]:
                if label == 'symlink':
                    info.type = tarfile.SYMTYPE
                    info.linkname = '../../escape'
                archive = root / (label + '.tar.xz')
                with tarfile.open(archive, 'w:xz') as bundle:
                    bundle.addfile(info)
                with self.assertRaises(RuntimeError):
                    thronesmac.extract_selected(archive, root / label, lambda name: name)
                self.assertFalse((root.parent / 'escape').exists())

    def test_valid_relative_symlinks_and_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / 'valid.tar.xz'
            with tarfile.open(archive, 'w:xz') as bundle:
                file = tarfile.TarInfo('lib/a')
                file.size = 4
                bundle.addfile(file, io.BytesIO(b'test'))
                link = tarfile.TarInfo('lib/b')
                link.type = tarfile.SYMTYPE
                link.linkname = 'a'
                bundle.addfile(link)
            thronesmac.extract_selected(archive, root / 'out', lambda name: name)
            self.assertEqual((root / 'out/lib/b').read_bytes(), b'test')

    def test_bad_cached_download_is_never_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / 'file').write_bytes(b'bad')
            with patch('urllib.request.urlopen') as request:
                with self.assertRaises(RuntimeError):
                    thronesmac.download({'filename': 'file', 'sha256': '0' * 64, 'url': 'https://example.com/file'}, cache)
                request.assert_not_called()


class GameTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'installation'
        self.root.mkdir()

    def test_documents_link_removed_without_touching_existing_saves(self):
        real = Path(self.temp.name) / 'real-documents'
        real.mkdir()
        save = real / 'prefs.prop'
        save.write_bytes(b'private progress')
        user = self.root / 'prefix/drive_c/users/player'
        user.mkdir(parents=True)
        (user / 'Documents').symlink_to(real)
        (user / 'My Documents').symlink_to('Documents')
        thronesmac.isolate_documents(self.root)
        self.assertEqual(save.read_bytes(), b'private progress')
        self.assertFalse((user / 'Documents').is_symlink())
        self.assertTrue((user / 'Documents').is_dir())
        self.assertEqual(list((user / 'Documents').iterdir()), [])
        self.assertFalse((user / 'My Documents').is_symlink())

    def test_unknown_dll_refused_before_destination_written(self):
        src, dst = self.root / 'unknown.dll', self.root / 'native.dll'
        src.write_bytes(b'MZ' + bytes(62) + b'Wine builtin DLL')
        with self.assertRaises(RuntimeError):
            thronesmac.native_d3d9(src, dst)
        self.assertFalse(dst.exists())
        self.assertIn(b'Wine builtin DLL', src.read_bytes())

    def test_existing_mod_is_not_overwritten(self):
        game = self.root / thronesmac.GAME_RELATIVE
        game.mkdir(parents=True)
        (game / 'Thrones.exe').write_bytes(b'placeholder')
        (game / 'd3d9.dll').write_bytes(b'existing mod')
        with self.assertRaises(RuntimeError):
            thronesmac.install_game_renderer(self.root)
        self.assertEqual((game / 'd3d9.dll').read_bytes(), b'existing mod')

    def test_external_game_folder_is_not_modified(self):
        game = self.root / thronesmac.GAME_RELATIVE
        game.parent.mkdir(parents=True)
        external = Path(self.temp.name) / 'outside'
        external.mkdir()
        game.symlink_to(external)
        with self.assertRaises(RuntimeError):
            thronesmac.install_game_renderer(self.root)
        self.assertEqual(list(external.iterdir()), [])

    def test_parent_graphics_and_wine_overrides_are_removed(self):
        with patch.dict('os.environ', {'WINEPREFIX':'/wrong','WINEARCH':'win32',
            'VK_DRIVER_FILES':'/wrong','CX_LIBVULKAN':'/wrong','DXVK_HUD':'full',
            'SteamAppId':'123'}):
            steam = thronesmac.wine_env(self.root)
            game = thronesmac.wine_env(self.root, game=True)
        self.assertEqual(game['WINEPREFIX'], str(self.root / 'prefix'))
        self.assertNotIn('WINEARCH', game)
        self.assertNotIn('DXVK_HUD', game)
        self.assertNotIn('VK_DRIVER_FILES', steam)
        self.assertNotIn('SteamAppId', steam)
        self.assertEqual(game['SteamAppId'], '330840')
        self.assertTrue(game['CX_LIBVULKAN'].endswith('libvulkan.1.4.350.dylib'))
        self.assertTrue(game['VK_DRIVER_FILES'].endswith('KosmicKrisp_icd.json'))
        self.assertEqual(game['VK_DRIVER_FILES'], game['VK_ICD_FILENAMES'])
        self.assertIn('d3d9=n,b', game['WINEDLLOVERRIDES'])

    def test_process_probe_is_in_selected_prefix(self):
        result = subprocess.CompletedProcess([], 0, '"Steam.exe","32"\n"Thrones.exe","80"\n')
        with patch('thronesmac.subprocess.run', return_value=result) as run:
            self.assertEqual(thronesmac.process_names(self.root), {'steam.exe','thrones.exe'})
        self.assertEqual(run.call_args.kwargs['env']['WINEPREFIX'], str(self.root / 'prefix'))

    def test_generated_app_handles_spaces_and_apostrophes(self):
        root = self.root / "a player's setup"
        (root / 'logs').mkdir(parents=True)
        (root / 'launcher').mkdir()
        (root / 'launcher/thronesmac.py').write_text('print("LAUNCH_OK")\n')
        app = self.root / 'sample.app'
        with patch('sys.executable', '/nonexistent/python3'):
            thronesmac.create_app(root, app)
        subprocess.run(['/bin/bash', str(app / 'Contents/MacOS/Launch')], check=True)
        self.assertIn('LAUNCH_OK', (root / 'logs/launcher.log').read_text())

    def test_refuses_foreign_installation(self):
        with self.assertRaises(RuntimeError):
            thronesmac.require_install(self.root)

    def test_old_macos_refused_before_runtime_runs(self):
        with patch('platform.system', return_value='Darwin'), patch('platform.mac_ver', return_value=('15.0','','')):
            with self.assertRaisesRegex(RuntimeError, '26 or later'):
                thronesmac.check_host()

    def test_prepare_does_not_overwrite_existing_root(self):
        import argparse
        sentinel = self.root / 'keep.txt'
        sentinel.write_text('keep')
        args = argparse.Namespace(root=self.root, app=self.root / 'test.app')
        with patch('thronesmac.check_host'), patch('thronesmac.download') as download:
            with self.assertRaises(RuntimeError):
                thronesmac.prepare(args)
            download.assert_not_called()
        self.assertEqual(sentinel.read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
