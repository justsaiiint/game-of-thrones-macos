#!/usr/bin/python3
"""Remove abandoned winedevice helpers from our game runtimes only.

A helper must be orphaned for 90 seconds with no other Wine process using its
runtime. Unknown process ownership blocks cleanup. Never closes Steam or games.
"""
import argparse
import datetime
import fcntl
import json
import hashlib
import plistlib
import sys
import tempfile
import os
from pathlib import Path
import signal
import subprocess
import time

BASE = Path(__file__).resolve().parent
ROOTS = (str(BASE.parent / 'runtime') + '/',)
GRACE = 90
TERM_GRACE = 30
WINE_NAMES = {'wine', 'wine64', 'wine-preloader', 'wine64-preloader', 'wineserver'}


def basename(command):
    return command.replace('\\', '/').rsplit('/', 1)[-1].lower()


def snapshot():
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,uid=,lstart=,comm='],
                            capture_output=True, text=True, timeout=10, check=True)
    records = []
    for line in result.stdout.splitlines():
        cols = line.split(None, 8)
        if len(cols) != 9 or int(cols[2]) != os.getuid():
            continue
        name = basename(cols[8])
        if not (name.endswith('.exe') or name in WINE_NAMES):
            continue
        records.append({'pid': int(cols[0]), 'ppid': int(cols[1]),
                        'start': ' '.join(cols[3:8]), 'name': name, 'group': None})
    if not records:
        return []
    # Resolve loaded Wine binaries rather than trusting argv or process labels.
    result = subprocess.run(['/usr/sbin/lsof', '-a', '-p',
                             ','.join(str(p['pid']) for p in records),
                             '-d', 'txt', '-Fn'], capture_output=True, text=True, timeout=15)
    if result.returncode not in (0, 1):
        raise RuntimeError('Unable to inspect Wine ownership')
    by_pid = {p['pid']: p for p in records}
    current = None
    for line in result.stdout.splitlines():
        if line.startswith('p') and line[1:].isdigit():
            current = by_pid.get(int(line[1:]))
        elif current is not None and line.startswith('n'):
            path = line[1:]
            if basename(path) in WINE_NAMES:
                for root in ROOTS:
                    if path.startswith(root):
                        current['group'] = root
                        break
    return records


def eligible(records):
    # A .exe whose ownership cannot be read could be a game. Fail closed.
    if any(p['group'] is None for p in records):
        return []
    candidates = []
    for p in records:
        if p['group'] not in ROOTS or p['name'] != 'winedevice.exe' or p['ppid'] != 1:
            continue
        others = [q for q in records if q['group'] == p['group']]
        if all(q['name'] == 'winedevice.exe' and q['ppid'] == 1 for q in others):
            candidates.append(p)
    return candidates


def identity(p):
    return '{}|{}|{}'.format(p['pid'], p['start'], p['group'])


def plan(records, previous, now):
    state, actions = {}, []
    for p in eligible(records):
        key = identity(p)
        entry = dict(previous.get(key, {'first_seen': now}))
        # Clock changes must not turn a fresh process into an old candidate.
        if now < entry['first_seen']:
            entry = {'first_seen': now}
        if now - entry['first_seen'] >= GRACE:
            if 'term_at' not in entry:
                actions.append((p, signal.SIGTERM))
            elif now - entry['term_at'] >= TERM_GRACE:
                actions.append((p, signal.SIGKILL))
        state[key] = entry
    return state, actions


def log(message):
    path = BASE / 'cleanup.log'
    if path.exists() and path.stat().st_size > 262144:
        path.replace(BASE / 'cleanup.previous.log')
    with path.open('a') as f:
        f.write('{} {}\n'.format(datetime.datetime.now().isoformat(timespec='seconds'), message))


def run(dry_run=False):
    records = snapshot()
    path = BASE / 'cleanup-state.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    now = time.time()
    state, actions = plan(records, previous, now)
    if dry_run:
        print(json.dumps({'processes': records, 'eligible_pids': [p['pid'] for p in eligible(records)],
                          'pending_actions': [{'pid': p['pid'], 'signal': int(sig)} for p, sig in actions]}, indent=2))
        return
    for p, sig in actions:
        # Recheck identity, ownership and active clients immediately before signalling.
        current = {identity(q): q for q in eligible(snapshot())}
        key = identity(p)
        if key not in current:
            state.pop(key, None)
            continue
        try:
            os.kill(p['pid'], sig)
        except ProcessLookupError:
            state.pop(key, None)
            continue
        log('{} orphan pid={} runtime={}'.format(signal.Signals(sig).name, p['pid'], p['group']))
        if sig == signal.SIGTERM:
            state[key]['term_at'] = now
        else:
            state.pop(key, None)
    # Idle checks do not rewrite state or logs.
    if state != previous:
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(state, indent=2) + '\n')
        temp.replace(path)


def agent_location(root):
    root = Path(root).resolve()
    suffix = hashlib.sha256(os.fsencode(root)).hexdigest()[:16]
    label = 'io.github.wine-games.cleanup.' + suffix
    return label, Path.home() / 'Library/LaunchAgents' / (label + '.plist')


def atomic_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.cleanup-')
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(data)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def launchctl(*args, check=True):
    return subprocess.run(['/bin/launchctl', *args], capture_output=True,
                          text=True, timeout=20, check=check)


def install(root):
    """Install or update one short-lived per-user check for this installation."""
    if sys.platform != 'darwin':
        raise RuntimeError('Automatic cleanup requires macOS')
    root = Path(root).resolve()
    if not (root / 'runtime').is_dir():
        raise RuntimeError('The installation runtime is missing')
    helper = root / 'maintenance/wine_cleanup.py'
    if helper.resolve().parent != root / 'maintenance':
        raise RuntimeError('Cleanup helper must stay inside the installation')
    label, agent = agent_location(root)
    domain = 'gui/{}'.format(os.getuid())
    data = plistlib.dumps({
        'Label': label,
        'ProgramArguments': [sys.executable, str(helper)],
        'RunAtLoad': True, 'StartInterval': 30,
        'ProcessType': 'Background', 'LowPriorityIO': True, 'Nice': 10,
    })
    # Read first, including when updating the already installed helper itself.
    code = Path(__file__).read_bytes()
    old_code = helper.read_bytes() if helper.exists() else None
    old_agent = agent.read_bytes() if agent.exists() else None
    loaded = launchctl('print', domain + '/' + label, check=False).returncode == 0
    if loaded:
        launchctl('bootout', domain + '/' + label)
    try:
        atomic_bytes(helper, code)
        atomic_bytes(agent, data)
        launchctl('bootstrap', domain, str(agent))
    except Exception:
        # Preserve an existing working registration if an update fails.
        for path, previous in [(helper, old_code), (agent, old_agent)]:
            if previous is None:
                if path.exists():
                    path.unlink()
            else:
                atomic_bytes(path, previous)
        if loaded and old_agent is not None:
            launchctl('bootstrap', domain, str(agent), check=False)
        raise
    return agent


def disable(root):
    """Remove only this installation's scheduled check; leave game data alone."""
    label, agent = agent_location(root)
    service = 'gui/{}/{}'.format(os.getuid(), label)
    if launchctl('print', service, check=False).returncode == 0:
        launchctl('bootout', service)
    if agent.exists():
        agent.unlink()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    BASE.mkdir(parents=True, exist_ok=True)
    with (BASE / 'cleanup.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            run(args.dry_run)
        except Exception as exc:
            log('Skipped cleanup: {}: {}'.format(type(exc).__name__, exc))
            raise


if __name__ == '__main__':
    main()
