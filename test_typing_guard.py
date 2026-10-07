"""Exercise typing, resume, shutdown restoration, and desktop-login startup."""
import configparser
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('typing_guard', ROOT / 'trackpad-typing-guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class TypingGuardTests(unittest.TestCase):
    def test_service_returns_after_desktop_login_and_restores_on_stop(self):
        service = configparser.ConfigParser(interpolation=None)
        service.read(ROOT / 'trackpad-typing-guard.service')
        self.assertEqual(service['Install']['WantedBy'], 'graphical-session.target')
        self.assertEqual(service['Unit']['PartOf'], 'graphical-session.target')
        self.assertEqual(service['Service']['Restart'], 'on-failure')
        self.assertEqual(service['Service']['ExecStart'],
                         '/usr/bin/python3 %h/.local/lib/trackpad-typing-guard.py run')
        self.assertEqual(service['Service']['ExecStopPost'],
                         '/usr/bin/python3 %h/.local/lib/trackpad-typing-guard.py restore')

    def test_shortcuts_and_removed_keyboards_do_not_leave_held_keys(self):
        activity = guard.Activity()
        activity.key('keyboard', 29, 1, 0)  # Ctrl
        activity.key('keyboard', 30, 1, 0)
        self.assertFalse(activity.active(0))
        activity.key('keyboard', 29, 0, 0)
        activity.key('keyboard', 30, 1, 1)
        self.assertTrue(activity.active(2))
        activity.remove('keyboard')
        self.assertFalse(activity.active(2))

    def test_running_guard_pauses_resumes_and_restores_without_real_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / 'state/omarchy/local-touchpads/settings.json'
            state.parent.mkdir(parents=True)
            state.write_text(json.dumps({'devices': {'apple': {
                'names': ['apple-inc.-magic-trackpad'],
                'settings': {'enabled': True, 'disable_while_typing': True}}}}))
            runtime = root / 'runtime'
            runtime.mkdir()
            status = runtime / 'trackpad-typing-guard.json'
            log = root / 'eval.jsonl'
            fake = root / 'hyprctl'
            fake.write_text('#!' + sys.executable + '''
import json, os, sys
from pathlib import Path
if sys.argv[1] == 'devices':
    print(json.dumps({'mice': [{'name': 'apple-inc.-magic-trackpad'},
                              {'name': 'ven_06cb:00-06cb:d01d-touchpad'}]}))
elif sys.argv[1] == 'eval':
    with Path(os.environ['GUARD_TEST_LOG']).open('a') as out:
        out.write(json.dumps(sys.argv[2]) + '\\n')
    print('ok')
else:
    raise SystemExit(2)
''')
            fake.chmod(0o700)
            read_fd, write_fd = os.pipe()
            env = dict(os.environ, XDG_STATE_HOME=str(root / 'state'),
                       XDG_RUNTIME_DIR=str(runtime), GUARD_TEST_LOG=str(log),
                       PATH=str(root) + os.pathsep + os.environ['PATH'])
            # Feed synthetic events through a pipe into the actual service loop.
            # No physical keyboard or compositor is opened by this test.
            runner = '''
import importlib.util, sys
spec = importlib.util.spec_from_file_location('guard', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.keyboards = lambda: {'/proc/self/fd/' + sys.argv[2]}
m.run()
'''
            process = subprocess.Popen([sys.executable, '-c', runner,
                                        str(ROOT / 'trackpad-typing-guard.py'), str(read_fd)],
                                       env=env, pass_fds=(read_fd,),
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            os.close(read_fd)

            def wait_for(predicate):
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    self.assertIsNone(process.poll(), 'Guard exited during typing test')
                    try:
                        result = json.loads(status.read_text())
                        if predicate(result):
                            return result
                    except FileNotFoundError:
                        pass
                    time.sleep(0.02)
                self.fail('Timed out waiting for typing protection')

            def key(value):
                os.write(write_fd, struct.pack('@llHHi', 0, 0, 1, 30, value))

            try:
                wait_for(lambda s: s['keyboards'] == 1)
                key(1)
                paused = wait_for(lambda s: s['paused'])
                self.assertEqual(set(paused), {'paused', 'keyboards', 'pauses',
                                             'resumes', 'protection', 'trackpad_enabled'})
                self.assertIn('enabled = false', log.read_text())
                key(0)
                wait_for(lambda s: not s['paused'] and s['resumes'] == 1)
                key(1)
                wait_for(lambda s: s['paused'] and s['pauses'] == 2)
                process.terminate()
                stdout, stderr = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, stdout + stderr)
                self.assertFalse(status.exists())
                commands = [json.loads(line) for line in log.read_text().splitlines()]
                self.assertIn('enabled = true', commands[-1])
                self.assertTrue(all('apple-inc.-magic-trackpad' in cmd for cmd in commands))
                self.assertTrue(all('d01d' not in cmd for cmd in commands))
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=5)
                os.close(write_fd)


if __name__ == '__main__':
    unittest.main()
