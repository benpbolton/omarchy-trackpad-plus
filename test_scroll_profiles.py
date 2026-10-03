import copy
import importlib.util
import json
import math
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).parent))
spec = importlib.util.spec_from_file_location('scroll_profiles', Path(__file__).with_name('scroll_profiles.py'))
s = importlib.util.module_from_spec(spec)
spec.loader.exec_module(s)
pp = s.pp

# Stand-in scroll curves until a Mac exports its HIDScrollAccelCurves: index, linear, parabolic,
# cubic, tangent_linear, tangent_root as 16.16 fixed point. Only their shape matters here.
STAND_IN_CURVES = [(0, 65536, 0, 0, 393216, 786432), (8192, 62259, 39322, 0, 406323, 786432),
                   (32768, 58982, 58982, 0, 419430, 786432), (65536, 49152, 104858, 0, 458752, 786432),
                   (196608, 36045, 157286, 0, 511181, 786432)]
# The constants measured from the 2026-10-03 recordings of MacBookPro18,3 (see tasks/results-mac-scrolling.md).
DRIVER = {'units_per_mm': 14.5, 'frame_rate_hz': 120.0, 'split_min': 1.0, 'points_per_unit': 10.0, 'release_ms': 50,
          'release_gain': 1.02, 'release_min': 60.0, 'momentum_table_hz': 0, 'verified': '', **s.DECAY}


def scroll(**changes):
    value = {'speed': 1.0, 'resolution': 400.0, 'report_rate_hz': 67.0, 'momentum_rate_hz': 120.0,
             'natural': False, 'driver': dict(DRIVER),
             'curves': [dict(zip(('index', 'linear', 'parabolic', 'cubic', 'tangent_linear', 'tangent_root'), row),
                             quartic=0) for row in STAND_IN_CURVES]}
    value.update(changes)
    return value


def profile(**changes):
    value = json.loads((Path(__file__).parent / 'tools/macos/profiles/MacBookPro18-3.json').read_text())
    value.update(version=2, scroll=scroll(**changes))
    return pp.validate_profile(value)


class LiteralAccelerator:
    """IOHIDScrollAccelerator::accelerate transcribed as C: fixed ring, explicit do … while."""

    def __init__(self, f, resolution, rate):
        self.f, self.resolution, self.rate = f, resolution, rate
        self.delta_time, self.scroll = [0.0] * 9, [0.0] * 9
        self._head = self._tail = 0
        self._direction = None
        self._last = None

    def accelerate(self, value, seconds, dispatch_rate=None):
        mult_momentum = dispatch_rate / 60.0 if dispatch_rate else 1.0
        scroll = value * mult_momentum
        deltaT = 1e18 if self._last is None else (seconds - self._last) * 1000
        self._last = seconds
        head = self._head
        self.delta_time[head] = deltaT
        self.scroll[head] = abs(scroll)
        self._head = (self._head + 1) % 9
        if self._head == self._tail:
            self._tail = (self._tail + 1) % 9
        direction = scroll > 0
        if self._direction != direction or deltaT > 500.0:
            self._tail = head
            self._direction = direction
        sumDeltaT = sumScroll = 0.0
        eventCount = 0
        i = self._head
        while True:
            i = (i if i else 9) - 1
            sumScroll += self.scroll[i]
            eventCount += 1
            if self.delta_time[i] > 150.0:
                sumDeltaT += 150.0
                break
            else:
                sumDeltaT += self.delta_time[i]
            if sumDeltaT >= 500.0:
                break
            if not i != self._tail:
                break
        rateMultiplier = self.rate / 67.0
        avargeDeltaTime = (sumDeltaT / eventCount) * rateMultiplier
        if avargeDeltaTime > 150.0:
            avargeDeltaTime = 150.0
        elif avargeDeltaTime < 1:
            avargeDeltaTime = 1
        avargeScroll = sumScroll / eventCount
        velocity = (2 / 65536 * avargeDeltaTime * avargeDeltaTime - 955 / 65536 * avargeDeltaTime
                    + 98369 / 65536) * avargeScroll * rateMultiplier
        if velocity < 1 / 65536:
            velocity = 1 / 65536
        deviceScale = self.resolution / self.rate
        multiplier = self.f(velocity / deviceScale) * (96.0 / 67.0)
        mult = multiplier / velocity
        return scroll * mult * (6554 / 65536) / mult_momentum


def webkit_table(initial, decay=s.DECAY):
    """MomentumEventDispatcher::buildOffsetTableWithInitialDelta's unaccelerated deltas at 60 Hz."""
    delta, table = list(initial), []
    while True:
        frame = 1 / 60
        velocity = math.hypot(*delta) / frame
        weak = max(0.0, (decay['decay_velocity'] - velocity) / decay['decay_velocity'])
        alpha = decay['decay_fast'] - (decay['decay_fast'] - decay['decay_slow']) * weak
        rate = alpha ** (frame / 0.008)
        delta = [delta[0] * rate, delta[1] * rate]
        table.append(tuple(delta))
        if not (abs(delta[0]) > 0.5 or abs(delta[1]) > 0.5):
            return table


class AcceleratorTests(unittest.TestCase):
    def setUp(self):
        self.profile = profile()
        self.f = s.scroll_function(self.profile)

    def test_matches_a_literal_transcription_event_by_event(self):
        rng = random.Random(5)
        for rate in [67.0, 120.0]:
            ours, theirs = s.ScrollAccelerator(self.f, 400.0, rate), LiteralAccelerator(self.f, 400.0, rate)
            t = 100.0
            for _ in range(4000):
                t += rng.choice([0.004, 0.008, 0.0081, 0.016, 0.12, 0.2, 0.6])
                delta = rng.choice([-1, 1, 1, 1]) * rng.uniform(0.2, 40)
                dispatch = rng.choice([None, None, 60.0, 120.0])
                self.assertAlmostEqual(ours.accelerate(delta, t, dispatch), theirs.accelerate(delta, t, dispatch),
                                       places=9)

    def test_first_event_counts_as_a_150_ms_interval(self):
        accelerator = s.ScrollAccelerator(self.f, 400.0, 67.0)
        velocity = (2 * 150 ** 2 - 955 * 150 + 98369) / 65536 * 10  # 119/65536 per unit
        self.assertAlmostEqual(velocity, 119 / 65536 * 10)
        expected = 10 * self.f(velocity * 67 / 400) * 96 / 67 / velocity * 6554 / 65536
        self.assertAlmostEqual(accelerator.accelerate(10, 1.0), expected)

    def test_steady_events_average_eight_intervals(self):
        accelerator = s.ScrollAccelerator(self.f, 400.0, 67.0)
        for index in range(20):
            out = accelerator.accelerate(5, 1 + index / 125)
        velocity = s.velocity_scale(8.0) * 5
        self.assertAlmostEqual(velocity / 5, 90857 / 65536, places=3)
        self.assertAlmostEqual(out, 5 * accelerator.multiplier(velocity) / velocity * s.PIXEL_TO_WHEEL)
        # The ring holds nine slots but keeps eight events: head never meets tail.
        self.assertEqual((accelerator.head - accelerator.tail) % 9, 8)

    def test_direction_change_and_long_gaps_clear_the_history(self):
        accelerator = s.ScrollAccelerator(self.f, 400.0, 67.0)
        for index in range(10):
            accelerator.accelerate(30, 1 + index / 125)
        reversed_out = accelerator.accelerate(-2, 1.08 + 0.008)
        alone = s.ScrollAccelerator(self.f, 400.0, 67.0)
        alone.accelerate(50, 0)
        self.assertAlmostEqual(reversed_out, alone.accelerate(-2, 0.016))
        resumed = accelerator.accelerate(-2, 1.088 + 0.6)  # > 500 ms: only this event
        self.assertAlmostEqual(resumed, s.ScrollAccelerator(self.f, 400.0, 67.0).accelerate(-2, 0))

    def test_momentum_is_scaled_to_60_hz_around_the_curve(self):
        a, b = s.ScrollAccelerator(self.f, 400.0, 67.0), s.ScrollAccelerator(self.f, 400.0, 67.0)
        for index in range(12):
            t = 1 + index / 120
            self.assertAlmostEqual(a.accelerate(3, t, 120.0), b.accelerate(6, t) / 2)

    def test_report_rate_moves_the_curve_and_the_interval(self):
        slow, fast = s.ScrollAccelerator(self.f, 400.0, 67.0), s.ScrollAccelerator(self.f, 400.0, 134.0)
        for index in range(12):
            low, high = slow.accelerate(4, index / 125), fast.accelerate(4, index / 125)
        self.assertNotAlmostEqual(low, high)
        self.assertAlmostEqual(fast.multiplier(1.0), self.f(134 / 400) * 96 / 67)


class MomentumTests(unittest.TestCase):
    def test_60_hz_frames_match_webkits_table(self):
        for initial in [(0, 40), (3, -25), (0, 6), (0, 0.4)]:
            frames = s.momentum((initial[0] * 60, initial[1] * 60), 60.0)
            self.assertAlmostEqual(frames[0][0], initial[0])
            self.assertAlmostEqual(frames[0][1], initial[1])
            table = webkit_table(initial)
            self.assertEqual(len(frames) - 1, len(table), initial)
            for ours, theirs in zip(frames[1:], table):
                self.assertAlmostEqual(ours[0], theirs[0], places=9)
                self.assertAlmostEqual(ours[1], theirs[1], places=9)

    def test_decay_is_fast_while_strong_and_slow_near_rest(self):
        frames = [f[1] for f in s.momentum((0, 3000), 120.0)]
        self.assertAlmostEqual(frames[1] / frames[0], 0.975 ** (1 / 120 / 0.008))
        self.assertLess(frames[-1] / frames[-2], 0.92 ** (1 / 120 / 0.008))
        self.assertLessEqual(abs(frames[-1]) * 120, 30)
        self.assertGreater(abs(frames[-2]) * 120, 30)

    def test_a_60_hz_table_keeps_its_distance_at_any_display_rate(self):
        for speed in [200, 1000, 4000]:
            low = s.momentum((0, speed), 60.0)
            for rate in [90.0, 120.0]:
                table = s.momentum((0, speed), rate, table_rate=60)
                self.assertAlmostEqual(sum(f[1] for f in table) / sum(f[1] for f in low), 1, places=9)
                self.assertAlmostEqual(len(table) / rate, len(low) / 60, delta=1 / rate)
                self.assertLess(max(f[1] for f in table), low[0][1])

    def test_direct_frames_glide_less_at_higher_rates(self):
        # Σ v·r^k·Δt overshoots ∫ v·e^(−λt) dt by about λ·Δt/2: ≈10 % at 60 Hz, ≈5 % at 120 Hz.
        for speed in [200, 1000, 4000]:
            low, high = s.momentum((0, speed), 60.0), s.momentum((0, speed), 120.0)
            ratio = sum(f[1] for f in high) / sum(f[1] for f in low)
            self.assertTrue(0.90 < ratio < 0.99, f'{speed}: {ratio}')
            self.assertAlmostEqual(len(high) / 120 / (len(low) / 60), 1, delta=0.12)


def stroke(speed, seconds=0.5, rate=120.0, start=1.0):
    """Finger frames for a steady vertical stroke at `speed` mm/s."""
    return [(start + k / rate, 0.0, speed / rate) for k in range(int(seconds * rate))]


class ContactTests(unittest.TestCase):
    def test_frames_split_into_two_events_once_they_move_enough(self):
        driver = dict(DRIVER, units_per_mm=10.0, split_min=1.0, frame_rate_hz=100.0)
        events = s.contact_events([(1.0, 0.0, 0.05), (1.01, 0.0, 0.2), (1.02, 0.0, 0.0), (1.03, -0.1, 0.0)], driver)
        self.assertEqual(len(events), 1 + 2 + 2)
        self.assertEqual(events[0], (1.0, 0.0, 0.5))                       # 0.5 units: one event
        self.assertAlmostEqual(events[1][0], 1.005)                         # half a frame earlier
        self.assertEqual(events[1][1:], (0.0, 1.0))
        self.assertEqual(events[2], (1.01, 0.0, 1.0))
        self.assertEqual([e[1] for e in events[3:]], [-0.5, -0.5])          # either axis can split

    def test_points_round_up_away_from_zero(self):
        self.assertEqual(s.points(0.0022, DRIVER), 1)
        self.assertEqual(s.points(-0.10014, DRIVER), -2)
        self.assertEqual(s.points(1.29726, DRIVER), 13)
        self.assertEqual(s.points(0.2, DRIVER), 2)        # exactly 2.0 stays 2
        self.assertEqual(s.points(0.0, DRIVER), 0)

    def test_release_is_the_mean_finger_velocity_of_the_last_frames(self):
        frames = stroke(40, seconds=0.2) + stroke(100, seconds=0.1, start=1.2)
        vx, vy = s.release_velocity(frames, DRIVER)
        self.assertEqual(vx, 0)
        # The last 50 ms are all at 100 mm/s: six frames of 100/120 mm, over 50 ms.
        self.assertAlmostEqual(vy, 6 * 100 / 120 * 14.5 * 1.02 / 0.05)


class SimulationTests(unittest.TestCase):
    def test_a_steady_stroke_reaches_the_static_curve(self):
        value = profile()
        for finger in [5, 40, 150, 400]:
            out = s.simulate(value, stroke(finger))
            per_second = sum(row[2] for row in out if 1.3 <= row[0] < 1.4) / 0.1
            unrounded = per_second * DRIVER['points_per_unit']
            self.assertAlmostEqual(unrounded / s.steady_points(value, finger, rounded=False), 1, delta=0.02,
                                   msg=f'{finger} mm/s')

    def test_apps_get_whole_points_and_at_least_one_per_event(self):
        out = s.simulate(profile(), stroke(3))
        moving = [row for row in out if row[2]]
        self.assertTrue(all(row[4] == math.ceil(row[2] * 10 - 1e-9) for row in moving))
        self.assertTrue(all(row[4] >= 1 for row in moving))
        self.assertGreater(sum(row[4] for row in moving), 10 * sum(row[2] for row in moving))

    def test_momentum_starts_only_above_the_release_minimum(self):
        value = profile()
        self.assertFalse(any(row[5] for row in s.simulate(value, stroke(0.2))))
        flick = s.simulate(value, stroke(150))
        momentum = [row for row in flick if row[5]]
        self.assertGreater(len(momentum), 30)
        self.assertTrue(all(row[2] > 0 and row[4] >= 1 for row in momentum))
        self.assertAlmostEqual(momentum[1][0] - momentum[0][0], 1 / 120)
        self.assertAlmostEqual(momentum[0][0], 1 + 59 / 120 + 1 / 120)    # one frame after the last


class ConversionTests(unittest.TestCase):
    def test_converts_to_64_increasing_points(self):
        result = s.convert(profile(), 98.65, 1.0)
        self.assertEqual(len(result['points']), 64)
        self.assertEqual(result['points'][0], 0)
        self.assertEqual(result['points'], sorted(result['points']))
        self.assertEqual(len(result['native'].split()), 65)
        self.assertFalse(result['native'].startswith('custom'))

    def test_samples_follow_the_steady_curve(self):
        value = profile()
        result = s.convert(value, 98.65, 1.0)
        for speed in [50, 100, 200]:  # above the one-point-per-event floor of slow strokes
            units = speed * 98.65 / 1000
            expected = s.steady_points(value, speed) / 1000
            self.assertAlmostEqual(pp.interpolate(result['step'], result['points'], units) / expected, 1, delta=0.02)
        self.assertLessEqual(result['error_bands']['30-300'], 1.5)

    def test_tail_is_exact_on_the_tangent_line(self):
        value = profile()
        result = s.convert(value, 98.65, 1.0)
        last = result['step'] * 63
        for factor in [1.0, 1.05]:
            units = last * factor
            expected = s.steady_points(value, units * 1000 / 98.65) / 1000
            self.assertAlmostEqual(pp.interpolate(result['step'], result['points'], units) / expected, 1, places=4)

    def test_scale_keeps_physical_travel(self):
        base, scaled = s.convert(profile(), 98.65, 1.0), s.convert(profile(), 98.65, 1.5)
        self.assertEqual(base['step'], scaled['step'])
        for low, high in zip(base['points'][1:], scaled['points'][1:]):
            self.assertAlmostEqual(high / low, 1.5, places=3)

    def test_unmeasured_profiles_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'scroll check'):
            s.convert(profile(driver=None), 98.65, 1.0)


class ValidationTests(unittest.TestCase):
    def rejects(self, value, message=''):
        with self.assertRaisesRegex(ValueError, message):
            pp.validate_profile(value)

    def test_version_2_requires_scrolling_and_version_1_forbids_it(self):
        value = profile()
        self.assertEqual(pp.load_profile(json.dumps(value).encode()), value)
        self.rejects(dict({k: v for k, v in value.items() if k != 'scroll'}), 'version 2')
        self.rejects(dict(value, version=1), 'version 2')
        self.rejects(dict(value, version=3), 'format')
        self.assertIsNone(profile(driver=None)['scroll']['driver'])

    def test_scroll_section_is_exact_and_bounded(self):
        value = profile()
        self.rejects(dict(value, scroll=dict(value['scroll'], extra=1)), 'scrolling')
        self.rejects(dict(value, scroll=dict(value['scroll'], natural=1)), 'scrolling')
        self.rejects(dict(value, scroll=dict(value['scroll'], speed=11)), 'range')
        self.rejects(dict(value, scroll=dict(value['scroll'], curves=[])), '1 to 16')
        self.rejects(dict(value, scroll=dict(value['scroll'], report_rate_hz=0)), 'range')
        driver = value['scroll']['driver']
        for change, message in [({'extra': 1}, 'constants'), ({'units_per_mm': 0}, 'range'),
                                ({'decay_fast': 1.2}, 'range'), ({'decay_slow': 0.99}, 'order'),
                                ({'verified': 'x' * 161}, 'text')]:
            broken = copy.deepcopy(value)
            broken['scroll']['driver'] = dict(driver, **change)
            self.rejects(broken, message)


if __name__ == '__main__':
    unittest.main()
