#!/usr/bin/env python3
"""Read and apply native palm settings for the supported Apple Magic Trackpad."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess

spec = importlib.util.spec_from_file_location('palm_system', Path(__file__).with_name('palm-system.py'))
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)
HELPER = Path('/usr/local/libexec/trackpad-plus-palm.py')


def supported_device():
    for event in Path('/sys/class/input').glob('event*'):
        try:
            device = event / 'device'
            if (device / 'name').read_text().strip() != 'Apple Inc. Magic Trackpad':
                continue
            vendor = int((device / 'id/vendor').read_text(), 16)
            product = int((device / 'id/product').read_text(), 16)
            if vendor in (0x004C, 0x05AC) and product == 0x0265:
                return True
        except (OSError, ValueError):
            continue
    return False


def session_started():
    try:
        result = subprocess.run(['hyprctl', 'instances', '-j'], capture_output=True, text=True, timeout=4)
        if result.returncode:
            return None
        signature = os.environ.get('HYPRLAND_INSTANCE_SIGNATURE')
        for instance in json.loads(result.stdout):
            if instance.get('instance') != signature:
                continue
            pid = int(instance['pid'])
            # After the final ')' the first token is field 3; starttime is field 22.
            ticks = int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19])
            boot = next(int(line.split()[1]) for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime '))
            return boot + ticks / os.sysconf('SC_CLK_TCK')
    except (OSError, ValueError, KeyError, StopIteration, subprocess.TimeoutExpired):
        pass
    return None


def state(device):
    if device != 'apple':
        return {'device': device, 'supported': False}
    try:
        text = rules.TARGET.read_text()
        changed = rules.TARGET.stat().st_mtime
    except FileNotFoundError:
        text, changed = '', 0
    threshold = rules.read_threshold(text)
    started = session_started()
    info = None
    try:info = HELPER.lstat()
    except FileNotFoundError:pass
    installed = bool(info and stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022)
    return {'device': device, 'supported': device == 'apple' and supported_device(),
            'mode': 'default' if threshold is None else 'custom', 'threshold': threshold or 900,
            'default_threshold': 900, 'pending': bool(changed and (started is None or changed > started)),
            'helper_installed': installed, 'model': 'Apple Magic Trackpad (0265)'}


def set_threshold(device, value):
    current = state(device)
    if not current['supported']:
        raise ValueError('Connect the supported Apple Magic Trackpad before changing palm rejection')
    if not current['helper_installed']:
        raise ValueError('The administrator helper has not been installed; see the README')
    rules.validate_threshold(value)
    result = subprocess.run(['pkexec', '/usr/bin/python3', '-I', '-B', str(HELPER),
                             'default' if value is None else str(value)],
                            capture_output=True, text=True, timeout=110)
    if result.returncode:
        try:message = json.loads(result.stdout).get('error')
        except (ValueError, AttributeError):message = None
        raise RuntimeError(message or 'Administrator authorization was cancelled or the setting could not be saved')
    return state(device)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['state', 'set'])
    parser.add_argument('device', choices=['apple', 'dell'])
    parser.add_argument('threshold', nargs='?')
    args = parser.parse_args()
    try:
        if args.action == 'state':result = state(args.device)
        else:
            if args.threshold is None:raise ValueError('Choose default or a palm threshold')
            value = None if args.threshold == 'default' else int(args.threshold)
            result = set_threshold(args.device, value)
        print(json.dumps(result))
    except Exception as error:
        print(json.dumps({'device': args.device, 'error': str(error)}))
        raise SystemExit(1)
