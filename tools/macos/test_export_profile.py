import contextlib
import importlib.util
import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location('export_profile', HERE / 'export-profile.py')
e = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e)
pp = e.pp
PROFILE = HERE / 'profiles' / 'MacBookPro18-3.json'


def recording(path, burst=0.0, rate=123.4, seed=7):
    """Synthesise a probe.swift CSV: steady strokes of whole counts, accelerated exactly as macOS does.

    `burst` > 0 makes counts alternate above and below the mean, like the attached driver.
    """
    profile = pp.load_profile(PROFILE.read_bytes())
    f = pp.apple_function(pp.apple_parameters(profile))
    driver = profile['driver']
    lines = ['# trackpad-plus probe 2', '# global_bounds,0.0,0.0,100000.0,100000.0']
    t, x, y = 1000.0, 50000.0, 50000.0
    period = 1 / rate
    for stroke, finger in enumerate([0.4, 0.7, 1.0, 1.5, 2.2, 3.0, 4.5, 6.5, 9.0] * 2):
        per_event, carried = 400 * finger / rate, 0.0
        angle = (stroke + seed) % 4 * math.pi / 2  # axis-aligned, so every |Δ| is a whole count
        for index in range(160):
            wobble = burst * per_event * (1 if index % 2 else -1)
            carried += per_event + wobble
            counts = math.floor(carried)
            carried -= counts
            t += period
            if not counts:
                continue
            ux, uy = round(counts * math.cos(angle)), round(counts * math.sin(angle))
            if not (ux or uy):
                continue
            dx, dy = pp.apple_event(f, ux, uy, period * 1000, driver)
            x, y = x + dx, y + dy
            lines.append(f'P,{t},{t},{x},{y},{round(dx)},{round(dy)},{ux},{uy},{float(ux)},{float(uy)},{round(dx)},{round(dy)}')
        t += 0.2
    path.write_text('\n'.join(lines) + '\n')


class CheckTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.profile = pp.load_profile(PROFILE.read_bytes())

    def check(self, **options):
        path = self.root / 'probe.csv'
        recording(path, **options)
        result = e.check_probe(self.profile, *e.read_probe(path))
        with contextlib.redirect_stdout(io.StringIO()):
            passed, worst, trusted = e.report_check(result)
        return result, passed, worst

    def test_native_strokes_pass_and_measure_the_event_rate(self):
        result, passed, worst = self.check()
        self.assertTrue(passed)
        self.assertAlmostEqual(result['driver']['event_rate_hz'], 123.4, places=1)
        self.assertFalse(result['fractional'])
        self.assertLess(result['median_error'], 0.01)
        self.assertLess(worst, 0.02)

    def test_bursty_counts_like_the_attached_driver_fail(self):
        result, passed, worst = self.check(burst=0.6)
        self.assertLess(result['median_error'], 0.01)  # the accelerator itself still matches
        self.assertFalse(passed)
        self.assertGreater(worst, 0.03)

    def test_write_stores_measured_constants_only_after_a_pass(self):
        probe, target = self.root / 'probe.csv', self.root / 'profile.json'
        recording(probe, rate=125.0)
        target.write_bytes(PROFILE.read_bytes())
        with mock.patch('sys.argv', ['export-profile.py', '--check', str(probe), '--profile', str(target), '--write']), \
                contextlib.redirect_stdout(io.StringIO()):
            e.main()
        driver = json.loads(target.read_text())['driver']
        self.assertEqual(driver['event_rate_hz'], 125.0)
        self.assertIn('accelerator median error', driver['verified'])
        recording(probe, burst=0.6)
        before = target.read_text()
        with mock.patch('sys.argv', ['export-profile.py', '--check', str(probe), '--profile', str(target), '--write']), \
                contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            e.main()
        self.assertEqual(target.read_text(), before)

    def test_short_recordings_are_rejected(self):
        path = self.root / 'short.csv'
        path.write_text('# global_bounds,0,0,10,10\nP,1,1,1,1,0,0,1,0,1.0,0.0,0,0\n')
        with self.assertRaises(SystemExit):
            e.read_probe(path)

    def test_shipped_profile_is_valid_and_verified(self):
        self.assertEqual(self.profile['tracking_speed'], 0.875)
        self.assertEqual(len(self.profile['curves']), 10)
        self.assertTrue(self.profile['driver']['verified'].startswith('probe '))


class ScrollExportTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def section(self, device, services, defaults=None):
        defaults = defaults or {}

        def ioreg(*arguments):
            return services.get(arguments[1], [])

        def run(*command):
            if command[-1] in defaults:
                return defaults[command[-1]]
            raise e.subprocess.CalledProcessError(1, command)
        with mock.patch.object(e, 'ioreg', ioreg), mock.patch.object(e, 'run', run), \
                contextlib.redirect_stdout(io.StringIO()):
            return e.scroll_section(device)

    def curves(self):
        return [{'HIDAccelIndex': 0, 'HIDAccelGainLinear': 65536, 'HIDAccelTangentSpeedLinear': 393216},
                {'HIDAccelIndex': 65536, 'HIDAccelGainLinear': 49152, 'HIDAccelGainParabolic': 104858,
                 'HIDAccelTangentSpeedLinear': 458752, 'HIDAccelTangentSpeedParabolicRoot': 786432}]

    def test_reads_curves_and_service_settings_as_iohidfamily_does(self):
        device = {'HIDScrollAccelCurves': self.curves(), 'HIDScrollResolution': 400 << 16}
        services = {'HIDEventServiceProperties': [{'HIDEventServiceProperties': {
            'HIDScrollAccelerationType': 'HIDTrackpadScrollAcceleration',
            'HIDTrackpadScrollAcceleration': 20480, 'ScrollMomentumDispatchRate': 120}}]}
        scroll = self.section(device, services, {'com.apple.swipescrolldirection': b'0\n'})
        self.assertEqual(scroll['speed'], 0.3125)
        self.assertEqual(scroll['resolution'], 400)
        self.assertEqual(scroll['report_rate_hz'], 67.0)  # FRAME_RATE without HIDScrollReportRate
        self.assertEqual(scroll['momentum_rate_hz'], 120.0)
        self.assertFalse(scroll['natural'])
        self.assertIsNone(scroll['driver'])
        self.assertEqual(scroll['curves'][1], {'index': 65536, 'linear': 49152, 'parabolic': 104858, 'cubic': 0,
                                               'quartic': 0, 'tangent_linear': 458752, 'tangent_root': 786432})

    def test_falls_back_to_user_defaults_and_macos_defaults(self):
        device = {'HIDScrollAccelCurves': self.curves(), 'HIDScrollResolution': 400 << 16,
                  'HIDScrollReportRate': 120 << 16}
        scroll = self.section(device, {}, {'com.apple.trackpad.scrolling': b'0.5\n'})
        self.assertEqual(scroll['speed'], 0.5)
        self.assertEqual(scroll['report_rate_hz'], 120.0)
        self.assertEqual(scroll['momentum_rate_hz'], 60.0)
        self.assertTrue(scroll['natural'])

    def test_missing_curves_or_disabled_acceleration_leave_pointer_only(self):
        self.assertIsNone(self.section({'HIDScrollResolution': 400 << 16}, {}))
        device = {'HIDScrollAccelCurves': self.curves(), 'HIDScrollResolution': 400 << 16,
                  'HIDTrackpadScrollAcceleration': -65536}
        self.assertIsNone(self.section(device, {}))

    def test_check_scroll_writes_the_driver_only_after_a_pass(self):
        spec = importlib.util.spec_from_file_location('test_scroll_check', HERE / 'test_scroll_check.py')
        synthetic = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(synthetic)
        probe, target = self.root / 'scroll.csv', self.root / 'profile.json'
        profile = synthetic.recording(probe)
        profile['scroll']['driver'] = None
        target.write_text(json.dumps(profile))
        argv = ['export-profile.py', '--check-scroll', str(probe), '--profile', str(target), '--write']
        with mock.patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()):
            e.main()
        driver = json.loads(target.read_text())['scroll']['driver']
        self.assertEqual(driver['release_ms'], 33)
        self.assertIn('accelerator median error', driver['verified'])
        output = io.StringIO()
        with mock.patch('sys.argv', ['export-profile.py', '--preview', str(target)]), contextlib.redirect_stdout(output):
            e.main()
        self.assertIn('scroll_points = "', output.getvalue())
        synthetic.recording(probe, accelerator_bias=1.05)
        before = target.read_text()
        with mock.patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
            e.main()
        self.assertEqual(target.read_text(), before)

    def test_pointer_only_profiles_cannot_be_scroll_checked(self):
        argv = ['export-profile.py', '--check-scroll', str(self.root / 'x.csv'), '--profile', str(PROFILE)]
        with mock.patch('sys.argv', argv), self.assertRaisesRegex(SystemExit, 'no scroll curves'):
            e.main()


if __name__ == '__main__':
    unittest.main()
