import contextlib
import importlib.util
import io
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

TRUTH = {'units_per_mm': 15.0, 'frame_rate_hz': 120.0, 'split_min': 1.0, 'points_per_unit': 10.0,
         'release_ms': 42, 'release_gain': 0.9, 'release_min': 300.0, 'momentum_table_hz': 0, 'verified': '',
         **sp.DECAY}
PAD_PT = (453.5, 283.5)  # 160 × 100 mm in NSTouch points
RATE = 120.0             # finger frames and momentum events per second


def recording(path, truth=TRUTH, accelerator_bias=1.0, seed=3):
    """Synthesise a scroll-probe.swift CSV from a known finger model, accelerated as macOS would.

    Fingers move along y in 120 Hz frames that NSTouch reports once per finger. Contact events
    come from the finger model; slow strokes stop before lifting; flicks speed up into the
    release and glide; some glides are stopped by a landing finger. The dispatch-rate
    attachment is left out, as on a real Mac, so the check must measure the momentum cadence.
    """
    profile = models.profile(driver=dict(truth))
    x_axis, y_axis = sp.accelerators(profile)
    rng = random.Random(seed)
    height_mm = PAD_PT[1] / 72 * 25.4
    lines = ['# trackpad-plus scroll-probe 1', '# natural,0', '# hid,1,children,1,attachment,1']
    t, offset = 1000.0, 0.0

    def scroll_row(seconds, phase, momentum, raw, accelerated, bits=0, count=1):
        nonlocal offset
        points = sp.points(accelerated, truth) if accelerated else 0.0
        offset += points
        lines.append(','.join(map(str, [
            'S', seconds, seconds, phase, momentum, 0.0, points, 1, 0, 0.0, raw, count, 0.0, points, 0.0,
            points / 10, 0.0, points / 10, 1, 0, 0, count, seconds, 0.0, raw, 0.0 if raw else '',
            accelerated if raw else '', 1, 0, 0, bits, ''])))
        lines.append(f'V,{seconds},0.0,{offset}')

    def touch(seconds, count, y_mm=50.0):
        fingers = []
        for index in range(count):
            fingers += [str(index + 1), str(0.4 + 0.2 * index), str(y_mm / height_mm), '2']
        row = ','.join(['N', str(seconds), str(seconds), str(count), str(PAD_PT[0]), str(PAD_PT[1])] + fingers)
        lines.extend([row, row] if count == 2 else [row])  # NSTouch repeats a frame per finger

    plans = [('stop', speed) for speed in (12, 25, 50, 90, 160)] * 3
    plans += [('flick', speed) for speed in (40, 70, 110, 160, 220, 300)] * 3
    plans += [('interrupt', speed) for speed in (150, 260)] * 3
    rng.shuffle(plans)
    for kind, speed in plans:
        sign = rng.choice([1, -1])
        y, frames = 50.0 - sign * 25, []
        touch(t, 2, y)
        count = rng.randint(40, 70)
        for k in range(count):
            t += 1 / RATE
            if kind == 'stop':  # slow to rest, then hold still for 100 ms before lifting
                fraction = max(0.0, min(1.0, (count - 12 - k) / (count / 3)))
            else:  # speed up into the release
                fraction = 0.3 + 0.7 * k / count
            step = sign * speed * fraction / RATE
            y += step
            touch(t, 2, y)
            frames.append((t, 0.0, step))
        events = sp.contact_events(frames, truth)
        for index, (seconds, _, raw) in enumerate(events):
            accelerated = y_axis.accelerate(raw, seconds) * accelerator_bias if raw else 0.0
            scroll_row(seconds, c.BEGAN if index == 0 else c.CHANGED, 0, raw, accelerated)
        lift = frames[-1][0] + 1 / RATE
        touch(lift, 0, y)
        scroll_row(lift, c.ENDED, 0, 0.0, 0.0)
        t = lift
        velocity = sp.release_velocity(frames, truth)
        if kind != 'stop' and math.hypot(*velocity) >= truth['release_min']:
            glide = sp.momentum(velocity, RATE, sp.constants(truth), truth['momentum_table_hz'])
            stop_at = len(glide) // 3 if kind == 'interrupt' else len(glide)
            for index, (_, dy) in enumerate(glide[:stop_at]):
                t = lift + index / RATE
                accelerated = y_axis.accelerate(dy, t, RATE) * accelerator_bias if dy else 0.0
                scroll_row(t, 0, c.BEGAN if index == 0 else c.CHANGED, dy, accelerated, bits=1 << 1)
            t += 1 / RATE
            if kind == 'interrupt':
                touch(t - 0.004, 1, y)
            scroll_row(t, 0, c.ENDED, 0.0, 0.0, bits=c.INTERRUPTED if kind == 'interrupt' else 1 << 3)
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

    def test_recovers_every_constant(self):
        result, passed, summary = self.check()
        self.assertTrue(passed)
        self.assertLess(result['momentum_accelerator'], 0.001)
        self.assertLess(result['start_accelerator'], 0.001)
        self.assertEqual(result['rounding'], 1.0)
        self.assertEqual(result['momentum_rate_hz'], RATE)  # measured: no attachment
        driver = result['driver']
        self.assertAlmostEqual(driver['units_per_mm'], 15.0, delta=0.1)
        self.assertEqual(driver['split_min'], 1.0)
        self.assertEqual(driver['frame_rate_hz'], RATE)
        self.assertEqual(driver['release_ms'], 42)
        self.assertAlmostEqual(driver['release_gain'], 0.9, delta=0.01)
        self.assertEqual(driver['momentum_table_hz'], 0)
        self.assertEqual(driver['decay_fast'], sp.DECAY['decay_fast'])
        self.assertLess(result['contact']['error'], 0.01)
        self.assertLess(result['momentum']['error'], 0.01)
        self.assertTrue(0 < driver['release_min'] < TRUTH['release_min'] * 3)
        self.assertAlmostEqual(result['view_ratio'], 1, places=2)
        self.assertTrue(result['interruption_ms'])
        self.assertIn('momentum accelerator', summary)
        for band, (ratio, count) in result['contact']['bands'].items():
            self.assertAlmostEqual(ratio, 1, delta=0.05, msg=band)
        models.profile(driver=dict(driver, verified=summary))  # a valid profile driver

    def test_a_60_hz_momentum_table_is_told_apart(self):
        result, passed, _ = self.check(truth=dict(TRUTH, momentum_table_hz=60))
        self.assertTrue(passed)
        self.assertEqual(result['driver']['momentum_table_hz'], 60)

    def test_a_different_accelerator_fails(self):
        result, passed, _ = self.check(accelerator_bias=1.05)
        self.assertGreater(result['momentum_accelerator'], 4)
        self.assertFalse(passed)

    def test_short_recordings_are_rejected(self):
        path = self.root / 'short.csv'
        path.write_text('# trackpad-plus scroll-probe 1\n')
        with self.assertRaises(SystemExit):
            c.read_recording(path)


if __name__ == '__main__':
    unittest.main()
