#!/usr/bin/env python3
"""Optional Apple trackpad typing guard. Never logs keyboard events."""
import argparse
import json
import os
from pathlib import Path
import selectors
import signal
import struct
import subprocess
import time

STATE = Path(os.environ.get('XDG_STATE_HOME') or Path.home() / '.local/state') / 'omarchy/local-touchpads/settings.json'
RUNTIME = Path(os.environ.get('XDG_RUNTIME_DIR', f'/run/user/{os.getuid()}'))
STATUS = RUNTIME / 'trackpad-typing-guard.json'
EVENT = struct.Struct('@llHHi')
MODIFIERS = {29, 56, 97, 100, 125, 126}  # Ctrl, Alt, Super; Shift allows typing.
IGNORED = MODIFIERS | {1, 42, 54, 55, 58}
PAUSE = 0.55


def hypr(*args):
    result = subprocess.run(['hyprctl', *args], capture_output=True, text=True, timeout=2)
    if result.returncode or (args[0] == 'eval' and result.stdout.strip() != 'ok'):
        raise RuntimeError('Desktop request failed')
    return result.stdout


def preferences():
    data = json.loads(STATE.read_text())
    group = data['devices']['apple']
    settings = group['settings']
    return set(group['names']), settings.get('enabled', True), settings.get('disable_while_typing', False)


def set_enabled(names, enabled):
    for name in sorted(names):
        # Literal strings only; never interpolate a device name as Lua code.
        hypr('eval', 'hl.device({ name = ' + json.dumps(name) + ', enabled = '
             + ('true' if enabled else 'false') + ' })')


def restore():
    try:
        names, enabled, _ = preferences()
        set_enabled(names, enabled)
        STATUS.unlink(missing_ok=True)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired):
        # Reload just configuration, preserving the monitor layout.
        hypr('reload', 'config-only')
        STATUS.unlink(missing_ok=True)


class Activity:
    def __init__(self):
        self.modifiers = set()
        self.held = set()
        self.until = 0.0

    def key(self, device, code, value, now):
        key = (device, code)
        if value == 0:
            self.modifiers.discard(key)
            if key in self.held:
                self.held.discard(key)
                self.until = now + PAUSE
        elif code in MODIFIERS:
            self.modifiers.add(key)
        elif value in (1, 2) and 2 <= code < 59 and code not in IGNORED and not self.modifiers:
            self.held.add(key)
            self.until = now + PAUSE

    def remove(self, device):
        self.modifiers = {key for key in self.modifiers if key[0] != device}
        self.held = {key for key in self.held if key[0] != device}

    def active(self, now):
        return bool(self.held) or now < self.until


def keyboards():
    """Discover physical devices with Q through P keys; exclude virtual keyboards."""
    found = set()
    for event in Path('/sys/class/input').glob('event*'):
        try:
            device = event / 'device'
            bus = int((device / 'id/bustype').read_text(), 16)
            words = (device / 'capabilities/key').read_text().split()
            word_bits = struct.calcsize('@L') * 8
            bits = sum(int(word, 16) << (index * word_bits)
                       for index, word in enumerate(reversed(words)))
            if bus in {0x03, 0x05, 0x11, 0x18, 0x1c} and all(bits & (1 << key) for key in range(16, 26)):
                found.add('/dev/input/' + event.name)
        except (OSError, ValueError):
            continue
    return found


def run():
    stopped = False

    def stop(*_):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    activity = Activity()
    devices = {}
    muted = set()
    buffers = {}
    next_scan = 0.0
    next_prefs = 0.0
    next_apply = 0.0
    names, enabled, protection = preferences()
    connected = set()
    pauses = 0
    resumes = 0
    with selectors.DefaultSelector() as selector:
        try:
            while not stopped:
                now = time.monotonic()
                if now >= next_scan:
                    detected = keyboards()
                    for path in set(devices) - detected:
                        fd = devices.pop(path)
                        selector.unregister(fd)
                        os.close(fd)
                        buffers.pop(fd, None)
                        activity.remove(path)
                    for path in detected - set(devices):
                        try:
                            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
                        except OSError:
                            continue
                        devices[path] = fd
                        buffers[fd] = b''
                        selector.register(fd, selectors.EVENT_READ, path)
                    connected = {row['name'] for row in json.loads(hypr('devices', '-j'))['mice']}
                    next_scan = now + 1.0
                if now >= next_prefs:
                    names, enabled, protection = preferences()
                    next_prefs = now + 0.25
                desired = names & connected if enabled and protection and activity.active(now) else set()
                released = muted - desired
                if released:
                    set_enabled(released, enabled)
                    resumes += 1
                if desired and (desired - muted or now >= next_apply):
                    set_enabled(desired, False)
                    if not muted:
                        pauses += 1
                    next_apply = now + 0.25
                muted = desired
                status = {'paused': bool(muted), 'keyboards': len(devices), 'pauses': pauses,
                          'resumes': resumes, 'protection': protection, 'trackpad_enabled': enabled}
                temporary = STATUS.with_suffix('.tmp')
                fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'w') as output:
                    json.dump(status, output)
                temporary.replace(STATUS)
                for event, _ in selector.select(0.04):
                    fd, path = event.fd, event.data
                    try:
                        raw = os.read(fd, EVENT.size * 64)
                        if not raw:
                            raise OSError('Disconnected')
                    except BlockingIOError:
                        continue
                    except OSError:
                        selector.unregister(fd)
                        os.close(fd)
                        devices.pop(path, None)
                        buffers.pop(fd, None)
                        activity.remove(path)
                        continue
                    raw = buffers[fd] + raw
                    complete = len(raw) // EVENT.size * EVENT.size
                    for offset in range(0, complete, EVENT.size):
                        _, _, kind, code, value = EVENT.unpack_from(raw, offset)
                        if kind == 1:
                            activity.key(path, code, value, time.monotonic())
                        elif kind == 0 and code == 3:  # SYN_DROPPED: don't trust held-key state.
                            activity.remove(path)
                    buffers[fd] = raw[complete:]
        finally:
            for fd in devices.values():
                os.close(fd)
            restore()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['run', 'restore', 'status'])
    action = parser.parse_args().action
    if action == 'run':
        run()
    elif action == 'restore':
        restore()
    else:
        print(STATUS.read_text() if STATUS.exists() else 'Not running')
