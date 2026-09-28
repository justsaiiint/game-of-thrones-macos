import importlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
app = importlib.import_module("thronesmac")

class CleanupIntegrationTests(unittest.TestCase):
    def test_existing_install_upgrade_preserves_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve()
            (root/app.MARKER).write_text(json.dumps({'project':"game-of-thrones-macos"}))
            (root/'save').write_bytes(b'progress')
            before={p.name:p.read_bytes() for p in root.iterdir()}
            with patch.object(app.wine_cleanup,'install',return_value=Path('/test/agent.plist')) as install:
                app.main(['cleanup-enable','--root',str(root)])
                install.assert_called_once_with(root)
            for name, data in before.items():
                self.assertEqual((root/name).read_bytes(),data)

    def test_enable_refuses_unmarked_root(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app.wine_cleanup,'install') as install:
            with self.assertRaises(RuntimeError):
                app.main(['cleanup-enable','--root',tmp])
            install.assert_not_called()

    def test_disable_still_works_after_installation_removed(self):
        with patch.object(app.wine_cleanup,'disable') as disable:
            app.main(['cleanup-disable','--root','/removed/game'])
            disable.assert_called_once_with(Path('/removed/game'))

    def preparation_probe(self, fail=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'install'
            app_path=Path(tmp)/'Game.app'
            fake=Path(tmp)/'archive'
            fake.write_bytes(b'installer')
            events=[]
            def extract(*args):
                (root/'runtime/Wine.app/Contents').mkdir(parents=True,exist_ok=True)
            def wine(*args,**kwargs):
                events.append('wine')
                if fail:
                    raise RuntimeError('Wine initialization failed')
            def install(root):
                self.assertTrue((root/app.MARKER).is_file())
                self.assertTrue(app_path.is_dir())
                events.append('cleanup')
            with patch.object(app,'check_host'), patch.object(app,'download',return_value=fake), patch.object(app,'extract_selected',side_effect=extract), patch.object(app.wine_cleanup,'install',side_effect=install), patch.object(app,'wine',side_effect=wine):
                from contextlib import ExitStack
                with ExitStack() as stack:
                    if hasattr(app,'native_d3d9'):
                        def renderer(*args):
                            (root/'runtime/game-of-thrones').mkdir(parents=True)
                        stack.enter_context(patch.object(app,'native_d3d9',side_effect=renderer))
                        stack.enter_context(patch.object(app,'isolate_documents'))
                    if hasattr(app,'require_game_closed'):
                        stack.enter_context(patch.object(app,'require_game_closed'))
                        stack.enter_context(patch.object(app,'configure'))
                    args=['prepare','--root',str(root),'--app',str(app_path)]
                    if hasattr(app,'default_resolution'):
                        args += ['--width','1920','--height','1080']
                    if fail:
                        with self.assertRaisesRegex(RuntimeError,'Wine initialization failed'):
                            app.main(args)
                    else:
                        app.main(args)
            self.assertEqual(events,['wine'] if fail else ['wine','wine','cleanup'])
            self.assertEqual((root/'launcher/wine_cleanup.py').read_bytes(),Path(app.wine_cleanup.__file__).read_bytes())

    def test_prepare_enables_cleanup_after_success(self):
        self.preparation_probe()

    def test_failed_prepare_does_not_register_agent(self):
        self.preparation_probe(fail=True)

if __name__ == '__main__':
    unittest.main()
