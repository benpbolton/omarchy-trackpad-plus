#!/usr/bin/env python3
"""Privileged writer for one supported Apple Magic Trackpad model only.

Install this file root-owned at /usr/local/libexec/trackpad-plus-palm.py.
The only writable target is /etc/libinput/local-overrides.quirks.
"""
import argparse
import configparser
import fcntl
import fnmatch
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time

TARGET = Path('/etc/libinput/local-overrides.quirks')
BEGIN = '# BEGIN Trackpad Plus Apple Magic Trackpad 0265'
END = '# END Trackpad Plus Apple Magic Trackpad 0265'
LEGACY = {'David Apple Magic Trackpad palm rejection': '0x004C',
          'David Apple Magic Trackpad USB palm rejection': '0x05AC'}


def validate_threshold(value):
    if value is not None and (type(value) is not int or not 50 <= value <= 1020):
        raise ValueError('Palm threshold must be an integer from 50 to 1020')


def sections(text):
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    parser.read_string(text)
    return parser


def strip_owned(text):
    count = text.count(BEGIN)
    if count != text.count(END) or count > 1:
        raise ValueError('Palm settings contain an incomplete managed block')
    if count:
        text, removed = re.subn(r'^' + re.escape(BEGIN) + r'\n.*?^' + re.escape(END) + r'\n?', '', text, flags=re.M | re.S)
        if removed != 1:
            raise ValueError('Palm settings contain an invalid managed block')
    parser = sections(text)
    for name, vendor in LEGACY.items():
        if name not in parser:
            continue
        values = dict(parser[name])
        threshold = values.pop('AttrPalmSizeThreshold', None)
        if values != {'MatchUdevType': 'touchpad', 'MatchVendor': vendor, 'MatchProduct': '0x0265'}:
            continue
        try:
            validate_threshold(int(threshold))
        except (ValueError, TypeError):
            continue
        text = re.sub(r'^\[' + re.escape(name) + r'\]\n.*?(?=^\[|\Z)', '', text, flags=re.M | re.S)
    return text


def check_conflicts(text):
    for name, values in sections(text).items():
        if name == 'DEFAULT' or 'AttrPalmSizeThreshold' not in values:
            continue
        if values.get('MatchUdevType', 'touchpad') != 'touchpad':
            continue
        if not fnmatch.fnmatchcase('Apple Inc. Magic Trackpad', values.get('MatchName', '*')):
            continue
        if values.get('MatchBus', 'bluetooth') not in ('bluetooth', 'usb'):
            continue
        vendor = values.get('MatchVendor', '').lower()
        product = values.get('MatchProduct', '').lower()
        if vendor in ('', '0x004c', '0x05ac') and product in ('', '0x0265'):
            raise ValueError('An existing palm rule also matches this Apple model; preserve it and resolve the conflict first')


def read_threshold(text):
    parser = sections(text)
    values = set()
    for name, row in parser.items():
        if name.startswith('Trackpad Plus Apple 0265 ') or name in LEGACY:
            threshold = int(row['AttrPalmSizeThreshold'])
            validate_threshold(threshold)
            values.add(threshold)
    if len(values) > 1:
        raise ValueError('The Apple USB and Bluetooth palm settings disagree')
    return next(iter(values), None)


def update_rules(text, value):
    validate_threshold(value)
    remaining = strip_owned(text)
    check_conflicts(remaining)
    lines = [BEGIN]
    if value is not None:
        for label, vendor in [('Bluetooth', '0x004C'), ('USB', '0x05AC')]:
            lines += [f'[Trackpad Plus Apple 0265 {label}]', 'MatchUdevType=touchpad',
                      f'MatchVendor={vendor}', 'MatchProduct=0x0265', f'AttrPalmSizeThreshold={value}', '']
    lines.append(END)
    return remaining.rstrip() + ('\n\n' if remaining.strip() else '') + '\n'.join(lines) + '\n'


def checked_read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'r') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
            raise ValueError('Palm configuration must be a private root-owned regular file')
        text = stream.read(1024 * 1024 + 1)
        if len(text) > 1024 * 1024:
            raise ValueError('Palm configuration exceeds the size limit')
        return text, stat.S_IMODE(info.st_mode)


def write_contents(fd, text, mode):
    with os.fdopen(fd, 'w') as stream:
        # pkexec may inherit a restrictive umask; retain readable configuration.
        os.fchmod(stream.fileno(), mode)
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())


def apply(value):
    if os.geteuid() != 0:
        raise PermissionError('Administrator authorization is required')
    info = TARGET.parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError('Input configuration directory is unsafe')
    lock = os.open(TARGET.parent / '.trackpad-plus-palm.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1 or info.st_mode & 0o022:
            raise ValueError('Input configuration lock is unsafe')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            original, mode = checked_read(TARGET)
        except FileNotFoundError:
            original, mode = '', 0o644
        updated = update_rules(original, value)
        if updated == original:
            return
        token = f'{int(time.time())}-{secrets.token_hex(4)}'
        if TARGET.exists():
            backup = TARGET.parent / f'local-overrides.quirks.trackpad-plus-backup-{token}'
            fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            write_contents(fd, original, 0o600)
        temporary = TARGET.parent / f'.trackpad-plus-palm-{token}'
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
            write_contents(fd, updated, mode)
            os.replace(temporary, TARGET)
            directory = os.open(TARGET.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:os.fsync(directory)
            finally:os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
    finally:
        os.close(lock)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('threshold', help='default, or an integer from 50 to 1020')
    args = parser.parse_args()
    try:
        value = None if args.threshold == 'default' else int(args.threshold)
        validate_threshold(value)
        apply(value)
        print(json.dumps({'ok': True}))
    except Exception as error:
        print(json.dumps({'error': str(error)}))
        raise SystemExit(1)
