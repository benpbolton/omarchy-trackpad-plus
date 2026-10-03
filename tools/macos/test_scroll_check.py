import contextlib
import importlib.util
import io
import json
import math
from pathlib import Path
import random
import sys
import tempfile
import unittest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parents[1]))
spec = importlib.util.spec_from_file_location('scroll_check', HERE / 'scroll_check.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
sp, pp = c.sp, c.pp
spec = importlib.util.spec_from_file_location('test_scroll_profiles', HERE.parents[1] / 'test_scroll_profiles.py')
models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(models)

TRUTH = {'units_per_mm': 12.5, 'event_rate_hz': 120.0, 'points_per_unit': 10.0, 'release_ms': 33,
         'release_gain': 1.15, 'release_min': 150.0, 'momentum_table_hz': 60, 'verified': '', **sp.DECAY}
PAD_PT = (453.5, 283.5)  # 160 × 100 mm in NSTouch points
DISPATCH = 120.0


def recording(path, truth=TRUTH, accelerator_bias=1.0, seed=3):
    """Synthesise a scroll-probe.swift CSV from a known driver, accelerated as macOS would.

    Strokes move both fingers along y. Slow strokes stop before lifting; flicks lift while
    moving and glide; some glides are stopped by a landing finger.
    """
    profile = models.profile(driver=dict(truth))
    x_axis, y_axis = sp.accelerators(profile)
    rng = random.Random(seed)
    height_mm = PAD_PT[1] / 72 * 25.4
    lines = ['# trackpad-plus scroll-probe 1', '# natural,0', '# hid,1,children,1,attachment,1']
    t, offset = 1000.0, 0.0
    period = 1 / truth['event_rate_hz']

    def scroll_row(seconds, phase, momentum, raw, accelerated, bits=0, rate=''):
        nonlocal offset
        points = accelerated * truth['points_per_unit']
        offset += points
        lines.append(','.join(map(str, [
            'S', seconds, seconds, phase, momentum, 0.0, points, 1, 0, 0.0, raw, 1, 0.0, round(points), 0.0,
            points / 10, 0.0, points / 10, 1, 0, 0, 1, seconds, 0.0, raw, 0.0 if raw else '',
            accelerated if raw else '', 1, 0, 0, bits, rate])))
        lines.append(f'V,{seconds},0.0,{offset}')

    def touch(seconds, count, y_mm=50.0):
        fingers = []
        for index in range(count):
            fingers += [str(index + 1), str(0.4 + 0.2 * index), str(y_mm / height_mm), '2']
        lines.append(','.join(['N', str(seconds), str(seconds), str(count), str(PAD_PT[0]), str(PAD_PT[1])] + fingers))

    plans = [('stop', speed) for speed in (8, 15, 30, 60, 120, 250)] * 2
    plans += [('flick', speed) for speed in (20, 40, 70, 110, 160, 220, 300, 420)] * 2
    plans += [('interrupt', speed) for speed in (150, 260, 380)] * 2
    rng.shuffle(plans)
    for kind, speed in plans:
        sign = rng.choice([1, -1])
        y, history = 50.0 - sign * 20, []
        touch(t, 2, y)
        events = rng.randint(30, 60)
        for k in range(events + 1):
            t += period
            # Stopping strokes slow down and rest for 100 ms before lifting; flicks speed up
            # into the release, which is what makes the release window measurable.
            if kind == 'stop':
                fraction = max(0.0, min(1.0, (events - 12 - k) / (events / 3)))
            else:
                fraction = 0.3 + 0.7 * k / events
            step = sign * speed * fraction * period
            y += step
            touch(t, 2, y)
            raw = step * truth['units_per_mm']
            phase = c.BEGAN if k == 0 else c.CHANGED
            accelerated = y_axis.accelerate(raw, t) * accelerator_bias if raw else 0.0
            scroll_row(t, phase, 0, raw, accelerated)
            history.append((t, 0.0, raw))
        t += period
        touch(t, 0, y)
        scroll_row(t, c.ENDED, 0, 0.0, 0.0)
        velocity = sp.release_velocity(history, truth)
        if math.hypot(*velocity) >= truth['release_min'] and kind != 'stop':
            frames = sp.momentum(velocity, DISPATCH, sp.constants(truth), truth['momentum_table_hz'])
            stop_at = len(frames) // 3 if kind == 'interrupt' else len(frames)
            for index, (_, dy) in enumerate(frames[:stop_at]):
                t += 1 / DISPATCH
                phase = c.BEGAN if index == 0 else c.CHANGED
                accelerated = y_axis.accelerate(dy, t, DISPATCH) * accelerator_bias if dy else 0.0
                scroll_row(t, 0, phase, dy, accelerated, bits=1 << 1, rate=DISPATCH)
            t += 1 / DISPATCH
            if kind == 'interrupt':
                touch(t - 0.004, 1, y)
            scroll_row(t, 0, c.ENDED, 0.0, 0.0, bits=c.INTERRUPTED if kind == 'interrupt' else 1 << 3, rate=DISPATCH)
        t += 0.8 + rng.random()
    Path(path).write_text('\n'.join(lines) + '\n')
    return profile


class ScrollCheckTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def check(self, **options):
        path = self.root / 'scroll.csv'
        profile = recording(path, **options)
        profile['scroll']['driver'] = None  # the check must not read the answer
        result = c.check_scroll(profile, c.read_recording(path))
        with contextlib.redirect_stdout(io.StringIO()):
            passed, summary = c.report(result)
        return result, passed, summary

    def test_recovers_every_driver_constant(self):
        result, passed, summary = self.check()
        self.assertTrue(passed)
        self.assertLess(result['median_error'], 0.01)
        driver = result['driver']
        self.assertAlmostEqual(driver['units_per_mm'] / TRUTH['units_per_mm'], 1, delta=0.01)
        self.assertAlmostEqual(driver['event_rate_hz'], 120.0, places=0)
        self.assertAlmostEqual(driver['points_per_unit'], 10.0, places=3)
        self.assertEqual(driver['release_ms'], 33)
        self.assertAlmostEqual(driver['release_gain'] / TRUTH['release_gain'], 1, delta=0.01)
        self.assertEqual(driver['momentum_table_hz'], 60)
        self.assertEqual(driver['decay_fast'], sp.DECAY['decay_fast'])
        self.assertLess(result['momentum']['error'], 0.01)
        self.assertLess(driver['release_min'], TRUTH['release_min'] * 1.5)
        self.assertGreater(driver['release_min'], 0)
        self.assertAlmostEqual(result['view_ratio'], 1, places=3)  # the first event has no prior offset
        self.assertTrue(result['interruption_ms'])
        self.assertIn('accelerator median error', summary)
        profile = models.profile(driver=dict(driver, verified=summary))
        self.assertEqual(profile['scroll']['driver']['release_ms'], 33)

    def test_direct_momentum_frames_are_told_apart(self):
        result, passed, _ = self.check(truth=dict(TRUTH, momentum_table_hz=0))
        self.assertTrue(passed)
        self.assertEqual(result['driver']['momentum_table_hz'], 0)

    def test_appkit_deltas_stand_in_when_hid_children_are_missing(self):
        path = self.root / 'scroll.csv'
        profile = recording(path)
        lines = []
        for line in path.read_text().splitlines():
            fields = line.split(',')
            if fields[0] == 'S':
                fields[25] = fields[26] = ''  # hid_accel_x, hid_accel_y
            lines.append(','.join(fields))
        path.write_text('\n'.join(lines) + '\n')
        result = c.check_scroll(profile, c.read_recording(path))
        self.assertIn('AppKit', result['reference'])
        self.assertLess(result['median_error'], 0.01)
        self.assertAlmostEqual(result['driver']['points_per_unit'], 10.0, places=3)

    def test_a_different_accelerator_fails(self):
        result, passed, _ = self.check(accelerator_bias=1.05)
        self.assertGreater(result['median_error'], 4)
        self.assertFalse(passed)

    def test_short_recordings_are_rejected(self):
        path = self.root / 'short.csv'
        path.write_text('# trackpad-plus scroll-probe 1\n')
        with self.assertRaises(SystemExit):
            c.read_recording(path)


if __name__ == '__main__':
    unittest.main()
