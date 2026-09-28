import json
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wine_cleanup as m
def proc(pid=111, name='winedevice.exe', group=m.ROOTS[0], ppid=1, start='Mon Sep 28 12:00:00 2026'):
    return dict(pid=pid, name=name, group=group, ppid=ppid, start=start)
class CleanupTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(m.plan([], {}, 100), ({}, []))
    def test_grace_and_escalation(self):
        p=proc(); key=m.identity(p)
        state, actions=m.plan([p], {}, 100)
        self.assertEqual(actions, [])
        self.assertEqual(m.plan([p], state, 189)[1], [])
        self.assertEqual(m.plan([p], state, 190)[1], [(p,signal.SIGTERM)])
        state[key]['term_at']=190
        self.assertEqual(m.plan([p], state, 219)[1], [])
        self.assertEqual(m.plan([p], state, 220)[1], [(p,signal.SIGKILL)])
    def test_active_clients_protected(self):
        for name in ['steam.exe','Sifu-Win64-Shipping.exe','eu5.exe','wineserver','wine','setup.exe','services.exe']:
            with self.subTest(name=name):
                self.assertEqual(m.eligible([proc(),proc(pid=112,name=name)]), [])
    def test_other_runtime_independent(self):
        p=proc()
        self.assertEqual(m.eligible([p,proc(pid=112,name='steam.exe',group='/other/runtime/')]), [p])
    def test_foreign_runtime_never_targeted(self):
        self.assertEqual(m.eligible([proc(group='/other/runtime/')]), [])

    def test_unknown_blocks(self):
        self.assertEqual(m.eligible([proc(),proc(pid=112,name='game.exe',group=None)]), [])
    def test_parent_protected(self):
        self.assertEqual(m.eligible([proc(ppid=99)]), [])
    def test_pid_reuse(self):
        state,_=m.plan([proc()],{},100)
        new=proc(start='Mon Sep 28 12:01:00 2026')
        newstate,actions=m.plan([new],state,1000)
        self.assertEqual(actions,[])
        self.assertEqual(newstate[m.identity(new)]['first_seen'],1000)
    def test_activity_resets_grace(self):
        state,_=m.plan([proc()],{},100)
        self.assertEqual(m.plan([proc(),proc(pid=112,name='steam.exe')],state,1000),({},[]))
    def test_clock_reversal(self):
        state,_=m.plan([proc()],{},100)
        newstate,actions=m.plan([proc()],state,50)
        self.assertEqual(actions,[])
        self.assertEqual(newstate[m.identity(proc())]['first_seen'],50)
    def test_collector(self):
        uid=m.os.getuid()
        ps='111 1 {} Mon Sep 28 12:00:00 2026 C:\\windows\\system32\\winedevice.exe\n112 1 {} Mon Sep 28 12:00:00 2026 /known/path/wineserver\n'.format(uid,uid)
        ls='p111\nn{}Wine11.app/Contents/lib/wine/x86_64-unix/wine\np112\nn{}Wine11.app/Contents/bin/wineserver\n'.format(m.ROOTS[0],m.ROOTS[0])
        with patch.object(m.subprocess,'run',side_effect=[SimpleNamespace(stdout=ps,returncode=0),SimpleNamespace(stdout=ls,returncode=0)]):
            records=m.snapshot()
        self.assertEqual(len(records),2)
        self.assertEqual(records[0]['name'],'winedevice.exe')
        self.assertTrue(all(p['group']==m.ROOTS[0] for p in records))
        self.assertEqual(m.eligible(records),[])
    def run_action_case(self, recheck, expected):
        p=proc()
        with tempfile.TemporaryDirectory() as d, patch.object(m,'BASE',Path(d)), patch.object(m.time,'time',return_value=1000), patch.object(m,'snapshot',side_effect=[[p],recheck]), patch.object(m.os,'kill') as kill:
            (Path(d)/'cleanup-state.json').write_text(json.dumps({m.identity(p):{'first_seen':100}}))
            m.run()
            if expected:
                kill.assert_called_once_with(111,signal.SIGTERM)
                self.assertEqual(json.loads((Path(d)/'cleanup-state.json').read_text())[m.identity(p)]['term_at'],1000)
            else:
                kill.assert_not_called()
    def test_recheck_new_activity(self):
        self.run_action_case([proc(),proc(pid=112,name='steam.exe')],False)
    def test_recheck_pid_changed(self):
        self.run_action_case([proc(start='changed')],False)
    def test_recheck_gone(self):
        self.run_action_case([],False)
    def test_confirmed_orphan_action(self):
        self.run_action_case([proc()],True)

class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cleanup space '")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.root = self.home / 'Game installation'
        (self.root / 'runtime').mkdir(parents=True)
        self.save = self.root / 'prefix/player.sav'
        self.save.parent.mkdir()
        self.save.write_bytes(b'keep game progress')
        self.home_patch = patch.object(m.Path, 'home', return_value=self.home)
        self.home_patch.start()
        self.addCleanup(self.home_patch.stop)
        self.platform_patch = patch.object(m.sys, 'platform', 'darwin')
        self.platform_patch.start()
        self.addCleanup(self.platform_patch.stop)

    @patch.object(m, 'launchctl')
    def test_install_repeat_custom_paths_and_disable(self, ctl):
        ctl.return_value = SimpleNamespace(returncode=1)
        agent = m.install(self.root)
        data = m.plistlib.loads(agent.read_bytes())
        self.assertEqual(data['ProgramArguments'], [m.sys.executable, str(self.root / 'maintenance/wine_cleanup.py')])
        self.assertEqual(data['StartInterval'], 30)
        self.assertNotIn('KeepAlive', data)
        self.assertEqual((self.root / 'maintenance/wine_cleanup.py').read_bytes(), Path(m.__file__).read_bytes())
        ctl.return_value = SimpleNamespace(returncode=0)
        self.assertEqual(m.install(self.root), agent)
        self.assertEqual(len(list(agent.parent.glob('*.plist'))), 1)
        m.disable(self.root)
        self.assertFalse(agent.exists())
        self.assertEqual(self.save.read_bytes(), b'keep game progress')
        m.disable(self.root)

    def test_separate_roots_get_separate_agents(self):
        self.assertNotEqual(m.agent_location(self.root),m.agent_location(self.home/'Other Game'))
        self.assertEqual(m.agent_location(self.root),m.agent_location(self.root/'.'))

    @patch.object(m, 'launchctl')
    def test_failed_update_restores_previous_installation(self, ctl):
        ctl.return_value = SimpleNamespace(returncode=1)
        agent = m.install(self.root)
        helper = self.root/'maintenance/wine_cleanup.py'
        helper.write_bytes(b'old version')
        previous_agent = agent.read_bytes()
        ctl.side_effect = [SimpleNamespace(returncode=0), SimpleNamespace(returncode=0), RuntimeError('bootstrap failed'), SimpleNamespace(returncode=0)]
        with self.assertRaisesRegex(RuntimeError,'bootstrap failed'):
            m.install(self.root)
        self.assertEqual(helper.read_bytes(),b'old version')
        self.assertEqual(agent.read_bytes(),previous_agent)

    @patch.object(m, 'launchctl')
    def test_failed_first_install_removes_registration(self, ctl):
        ctl.side_effect = [SimpleNamespace(returncode=1),RuntimeError('bootstrap failed')]
        with self.assertRaises(RuntimeError):
            m.install(self.root)
        self.assertFalse(m.agent_location(self.root)[1].exists())
        self.assertFalse((self.root/'maintenance/wine_cleanup.py').exists())
        self.assertEqual(self.save.read_bytes(),b'keep game progress')

    @patch.object(m, 'launchctl')
    def test_missing_runtime_or_external_helper_refused(self, ctl):
        with self.assertRaises(RuntimeError):
            m.install(self.home/'missing')
        outside = self.home/'outside'
        outside.mkdir()
        (self.root/'maintenance').symlink_to(outside)
        with self.assertRaises(RuntimeError):
            m.install(self.root)
        ctl.assert_not_called()

    @patch.object(m.os, 'kill')
    def test_failed_collection_does_not_signal(self, kill):
        with patch.object(m,'snapshot',side_effect=RuntimeError('collector failed')):
            with self.assertRaises(RuntimeError):
                m.run()
        kill.assert_not_called()

if __name__ == '__main__':
    unittest.main()
