"""Check a scroll-probe.swift recording against Apple's scroll accelerator and measure the driver.

Apple's IOHIDScrollAccelerator is open source, so it must reproduce the accelerated value of
every recorded event before anything else is trusted. The closed multitouch driver is then
measured: raw scroll units per mm of finger travel, its event rate, how the release sets the
first momentum delta, and the momentum decay. Used by export-profile.py --check-scroll.
"""
import math
from pathlib import Path
import statistics
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import pointer_profiles as pp  # noqa: E402
import scroll_profiles as sp  # noqa: E402

BEGAN, STATIONARY, CHANGED, ENDED, CANCELLED = 1, 2, 4, 8, 16  # NSEvent.Phase
SCROLL_COLUMNS = ('timestamp received phase momentum_phase scrolling_dx scrolling_dy precise inverted '
                  'unaccel_dx unaccel_dy scroll_count cg_point_dx cg_point_dy cg_fixed_dx cg_fixed_dy '
                  'cg_line_dx cg_line_dy cg_continuous cg_scroll_phase cg_momentum_phase cg_scroll_count '
                  'hid_time hid_raw_x hid_raw_y hid_accel_x hid_accel_y hid_children hid_flags hid_phase '
                  'hid_momentum hid_dispatch_rate').split()
INTERRUPTED = 1 << 4  # kIOHIDEventScrollMomentumInterrupted
RELEASE_WINDOWS_MS = (8, 12, 16, 25, 33, 50, 66, 83, 100, 133, 166, 200, 250)
MIN_EVENTS, MIN_STROKES, MIN_FLICKS = 500, 5, 8
POINTS_PER_INCH = 72.0  # NSTouch.deviceSize


def number(text):
    return float(text) if text else math.nan


def read_recording(path):
    """Rows from scroll-probe.swift: scroll events, two-finger touch frames, and view offsets."""
    scroll, touches, view, header = [], [], [], {}
    for line in Path(path).read_text().splitlines():
        fields = line.split(',')
        if line.startswith('# ') and len(fields) > 1 and not line.startswith('# columns'):
            header[fields[0][2:]] = fields[1:]
        elif fields[0] == 'S' and len(fields) == len(SCROLL_COLUMNS) + 1:
            scroll.append(dict(zip(SCROLL_COLUMNS, map(number, fields[1:]))))
        elif fields[0] == 'N' and len(fields) >= 6:
            fingers = [(fields[i], float(fields[i + 1]), float(fields[i + 2])) for i in range(6, len(fields) - 3, 4)]
            touches.append((float(fields[1]), int(fields[3]), float(fields[4]), float(fields[5]), fingers))
        elif fields[0] == 'V':
            view.append(tuple(map(float, fields[1:4])))
    if len(scroll) < 200:
        raise SystemExit(f'{path} has too few scroll events; record again for the full two minutes.')
    return {'scroll': scroll, 'touches': touches, 'view': view, 'header': header}


def strokes(rows):
    """Contact phases from Began to Ended, each with the momentum sequence that follows it.

    MayBegin events (resting fingers) belong to no stroke.
    """
    found, current = [], None
    for row in rows:
        phase = row['phase']
        if phase == BEGAN:
            current = {'contact': [row], 'momentum': []}
            found.append(current)
        elif phase in (STATIONARY, CHANGED, ENDED, CANCELLED) and current is not None:
            current['contact'].append(row)
            if phase in (ENDED, CANCELLED):
                current = None
        elif row['momentum_phase'] and found:
            found[-1]['momentum'].append(row)
    return found


def axis(rows, key):
    """The dominant axis of a stroke: 'x' or 'y'."""
    x = sum(abs(r[f'{key}_x']) for r in rows if math.isfinite(r[f'{key}_x']))
    y = sum(abs(r[f'{key}_y']) for r in rows if math.isfinite(r[f'{key}_y']))
    return 'x' if x > y else 'y'


def check_accelerator(profile, rows):
    """Replay every raw delta through ScrollAccelerator; compare with Apple's accelerated child.

    Without accelerated children (CGEventCopyIOHIDEvent may drop them), AppKit's precise
    deltas are the reference instead, normalised by their median ratio, since a correct model
    leaves only a constant points-per-unit factor. Returns (sorted errors in %, reference,
    that ratio or None).
    """
    x_axis, y_axis = sp.accelerators(profile)
    errors, fallback = [], []
    for row in rows:
        if not math.isfinite(row['hid_time']):
            continue
        momentum = row['hid_momentum'] > 0 if math.isfinite(row['hid_momentum']) else bool(row['momentum_phase'])
        rate = row['hid_dispatch_rate'] if momentum and math.isfinite(row['hid_dispatch_rate']) else None
        for name, accelerator in (('x', x_axis), ('y', y_axis)):
            raw, actual = row[f'hid_raw_{name}'], row[f'hid_accel_{name}']
            if not math.isfinite(raw) or not raw:
                continue
            predicted = accelerator.accelerate(raw, row['hid_time'], rate)
            if math.isfinite(actual) and abs(actual) > 1e-6:
                errors.append(abs(predicted / actual - 1) * 100)
            points = row[f'scrolling_d{name}']
            if abs(points) > 0.05 and not row['scroll_count'] > 1:
                fallback.append(abs(points / predicted))
    if len(errors) < 50 and fallback:
        scale = statistics.median(fallback)
        return sorted(abs(ratio / scale - 1) * 100 for ratio in fallback), 'AppKit deltas (no HID children)', scale
    return sorted(errors), 'HID accelerated values', None



def ratios(rows, numerator, denominator):
    values = []
    for row in rows:
        for name in ('x', 'y'):
            top, bottom = row[f'{numerator}{name}'], row[f'{denominator}{name}']
            if math.isfinite(top) and math.isfinite(bottom) and abs(bottom) > 0.05:
                values.append(abs(top / bottom))
    return values


def centroid(touches):
    """Two-finger centroid in mm over time, from NSTouch's normalised positions."""
    track = []
    for seconds, touching, width, height, fingers in touches:
        if touching == 2 and len(fingers) == 2 and width > 0 and height > 0:
            x = sum(f[1] for f in fingers) / 2 * width / POINTS_PER_INCH * 25.4
            y = sum(f[2] for f in fingers) / 2 * height / POINTS_PER_INCH * 25.4
            track.append((seconds, x, y))
    return track


def position(track, seconds, name):
    """Linear interpolation of the centroid on one axis; None outside the track."""
    index = {'x': 1, 'y': 2}[name]
    low, high = 0, len(track) - 1
    if not track or seconds < track[0][0] or seconds > track[-1][0]:
        return None
    while high - low > 1:
        middle = (low + high) // 2
        if track[middle][0] <= seconds:
            low = middle
        else:
            high = middle
    a, b = track[low], track[high]
    if b[0] == a[0]:
        return a[index]
    return a[index] + (b[index] - a[index]) * (seconds - a[0]) / (b[0] - a[0])


def fit_line(xs, ys):
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if not sxx:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    syy = sum((y - my) ** 2 for y in ys)
    r2 = slope * slope * sxx / syy if syy else 0
    return slope, my - slope * mx, r2


def measure_contact(found, track):
    """Raw units per finger mm from each long stroke, and the contact event rate."""
    slopes, gaps = [], []
    for stroke in found:
        rows = [r for r in stroke['contact'] if math.isfinite(r['hid_time'])]
        if len(rows) < 15:
            continue
        name = axis(rows, 'hid_raw')
        gaps += [b['hid_time'] - a['hid_time'] for a, b in zip(rows, rows[1:])
                 if b['phase'] == CHANGED and 0 < b['hid_time'] - a['hid_time'] < 0.05]
        raw, fingers, total = [], [], 0.0
        for row in rows:
            total += row[f'hid_raw_{name}'] or 0.0
            finger = position(track, row['timestamp'], name)
            if finger is not None:
                raw.append(total)
                fingers.append(finger)
        if len(raw) < 15 or max(fingers) - min(fingers) < 15:
            continue
        line = fit_line(fingers[3:], raw[3:])
        if line and line[2] > 0.95:
            slopes.append(abs(line[0]))
    rate = 1 / statistics.median(gaps) if gaps else math.nan
    return slopes, rate


def contact_history(stroke):
    """Moving contact deltas, as scroll_profiles.release_velocity expects: not the Ended event."""
    return [(r['hid_time'], r['hid_raw_x'] or 0.0, r['hid_raw_y'] or 0.0) for r in stroke['contact']
            if r['phase'] not in (ENDED, CANCELLED) and math.isfinite(r['hid_time']) and math.isfinite(r['hid_raw_y'])]


def momentum_rows(stroke):
    return [r for r in stroke['momentum'] if math.isfinite(r['hid_time']) and math.isfinite(r['hid_raw_y'])]


def momentum_rate(rows):
    gaps = [b['hid_time'] - a['hid_time'] for a, b in zip(rows, rows[1:]) if b['hid_time'] > a['hid_time']]
    return 1 / statistics.median(gaps) if gaps else math.nan


def interrupted(rows):
    return any(math.isfinite(r['hid_momentum']) and int(r['hid_momentum']) & INTERRUPTED for r in rows)


def fit_release(found):
    """The contact window and gain that best predict each flick's first momentum delta."""
    flicks, still = [], []
    for stroke in found:
        history, rows = contact_history(stroke), momentum_rows(stroke)
        if len(history) < 3:
            continue
        if rows and len(rows) > 2:
            rate = rows[0]['hid_dispatch_rate'] if math.isfinite(rows[0]['hid_dispatch_rate']) else momentum_rate(rows)
            first = (rows[0]['hid_raw_x'] * rate, rows[0]['hid_raw_y'] * rate)
            flicks.append((history, first))
        elif not stroke['momentum']:
            still.append(history)
    best = None
    for window in RELEASE_WINDOWS_MS:
        driver = {'release_ms': window, 'release_gain': 1.0}
        gains = []
        for history, first in flicks:
            released = math.hypot(*sp.release_velocity(history, driver))
            if released > 0:
                gains.append(math.hypot(*first) / released)
        if len(gains) < 3:
            continue
        logs = [math.log(g) for g in gains]
        spread = statistics.pstdev(logs)
        if best is None or spread < best[0]:
            best = (spread, window, statistics.median(gains), len(gains))
    if best is None:
        return None
    _, window, gain, count = best
    driver = {'release_ms': window, 'release_gain': gain}
    started = [math.hypot(*sp.release_velocity(h, driver)) for h, _ in flicks]
    stopped = [math.hypot(*sp.release_velocity(h, driver)) for h in still]
    low, high = min(started), max(stopped, default=0.0)
    minimum = (low + high) / 2 if high < low else low
    return {'release_ms': window, 'release_gain': gain, 'release_min': minimum, 'flicks': count,
            'spread': best[0], 'separable': high < low}


def momentum_error(rows, decay, table_rate):
    """Distance and duration of a measured momentum sequence against the model, as ratios."""
    rate = rows[0]['hid_dispatch_rate'] if math.isfinite(rows[0]['hid_dispatch_rate']) else momentum_rate(rows)
    if not math.isfinite(rate):
        return None
    first = (rows[0]['hid_raw_x'] * rate, rows[0]['hid_raw_y'] * rate)
    frames = sp.momentum(first, rate, decay, table_rate)
    measured = sum(math.hypot(r['hid_raw_x'] or 0, r['hid_raw_y'] or 0) for r in rows)
    modelled = sum(math.hypot(*f) for f in frames)
    if not measured:
        return None
    return modelled / measured, len(frames) / len(rows), rate


def fit_momentum(found):
    """Choose the table mode, and refit the decay only if WebKit's constants miss."""
    sequences = [rows for rows in map(momentum_rows, found) if len(rows) > 5 and not interrupted(rows)]
    if len(sequences) < 3:
        return None

    def score(decay, table_rate):
        results = [momentum_error(rows, decay, table_rate) for rows in sequences]
        results = [r for r in results if r]
        errors = sorted(abs(r[0] - 1) for r in results)
        return (errors[len(errors) // 2] if errors else math.inf), results

    candidates = []
    for table_rate in (0, 60):
        error, results = score(sp.DECAY, table_rate)
        candidates.append((error, dict(sp.DECAY), table_rate, results))
    error, decay, table_rate, results = min(candidates, key=lambda c: c[0])
    if error > 0.03:
        for fast in [0.96 + 0.0025 * i for i in range(11)]:
            for slow in [0.86 + 0.005 * i for i in range(19)]:
                if slow > fast:
                    continue
                trial = dict(sp.DECAY, decay_fast=round(fast, 4), decay_slow=round(slow, 4))
                trial_error, trial_results = score(trial, table_rate)
                if trial_error < error:
                    error, decay, results = trial_error, trial, trial_results
    rates = [r[2] for r in results]
    durations = sorted(r[1] for r in results)
    return {'decay': decay, 'momentum_table_hz': table_rate, 'error': error, 'sequences': len(results),
            'rate_hz': statistics.median(rates), 'duration_ratio': durations[len(durations) // 2],
            'modes': {mode: candidate[0] for candidate, mode in zip(candidates, (0, 60))}}


def interruption_latency(found, touches):
    """Milliseconds from a finger landing to the end of the momentum it stopped."""
    landings = [seconds for (seconds, touching, *_), (_, before, *_) in zip(touches[1:], touches)
                if touching > before]
    latencies = []
    for stroke in found:
        rows = stroke['momentum']
        if not rows or not interrupted(momentum_rows(stroke)):
            continue
        start, end = rows[0]['timestamp'], rows[-1]['timestamp']
        landed = [t for t in landings if start <= t <= end]
        if landed:
            latencies.append((end - landed[0]) * 1000)
    return latencies


def view_ratio(recording):
    """How far the scroll view moved per point of AppKit scrolling delta."""
    moved = sum(abs(b[2] - a[2]) + abs(b[1] - a[1]) for a, b in zip(recording['view'], recording['view'][1:]))
    deltas = sum(abs(r['scrolling_dx']) + abs(r['scrolling_dy']) for r in recording['scroll'])
    return moved / deltas if deltas else math.nan


def check_scroll(profile, recording):
    rows = recording['scroll']
    found = strokes(rows)
    track = centroid(recording['touches'])
    errors, reference, fallback_scale = check_accelerator(profile, rows)
    contact = [r for s in found for r in s['contact']]
    appkit = ratios([r for r in contact if r['scroll_count'] <= 1 or not math.isfinite(r['scroll_count'])],
                    'scrolling_d', 'hid_accel_')
    boost = {}
    for row in rows:
        count = row['scroll_count']
        if math.isfinite(count) and count >= 1:
            boost.setdefault(int(count), []).extend(ratios([row], 'scrolling_d', 'hid_accel_'))
    slopes, event_rate = measure_contact(found, track)
    release = fit_release(found)
    momentum = fit_momentum(found)
    result = {
        'events': len(errors), 'strokes': len(found), 'reference': reference,
        'median_error': errors[len(errors) // 2] if errors else math.nan,
        'within_half_percent': sum(e < 0.5 for e in errors) / len(errors) if errors else 0,
        'points_per_unit': statistics.median(appkit) if appkit else fallback_scale or math.nan,
        'cg_points_per_unit': statistics.median(ratios(contact, 'cg_point_d', 'hid_accel_') or [math.nan]),
        'boost': {count: statistics.median(values) for count, values in sorted(boost.items()) if len(values) >= 5},
        'units_per_mm': statistics.median(slopes) if slopes else math.nan,
        'units_spread': (statistics.quantiles(slopes, n=4)[2] - statistics.quantiles(slopes, n=4)[0])
        / statistics.median(slopes) if len(slopes) >= 4 else math.nan,
        'measured_strokes': len(slopes), 'event_rate_hz': round(event_rate, 1) if math.isfinite(event_rate) else math.nan,
        'release': release, 'momentum': momentum,
        'interruption_ms': interruption_latency(found, recording['touches']),
        'view_ratio': view_ratio(recording),
        'natural': recording['header'].get('natural', ['?'])[0] == '1',
    }
    result['driver'] = driver_from(result)
    return result


def driver_from(result):
    release, momentum = result['release'], result['momentum']
    if not (release and momentum and math.isfinite(result['units_per_mm'])
            and math.isfinite(result['event_rate_hz']) and math.isfinite(result['points_per_unit'])):
        return None
    return {'units_per_mm': round(result['units_per_mm'], 4), 'event_rate_hz': result['event_rate_hz'],
            'points_per_unit': round(result['points_per_unit'], 4), 'release_ms': release['release_ms'],
            'release_gain': round(release['release_gain'], 4), 'release_min': round(release['release_min'], 2),
            'momentum_table_hz': momentum['momentum_table_hz'], 'verified': '',
            **{key: momentum['decay'][key] for key in sp.DECAY}}


def report(result):
    """Print the findings; return (passed, summary for the profile)."""
    print(f"Scroll events: {result['strokes']} strokes; contact events at {result['event_rate_hz']} Hz.")
    print(f"Apple's scroll accelerator, event by event against {result['reference']}: median error "
          f"{result['median_error']:.2f} % over {result['events']} values ({result['within_half_percent']:.0%} within 0.5 %).")
    print(f"Points per accelerated unit: AppKit {result['points_per_unit']:.3f}, CGEvent {result['cg_points_per_unit']:.3f}; "
          f"scroll view moved {result['view_ratio']:.3f} points per AppKit point.")
    if result['boost']:
        print('AppKit points per unit by scroll count: '
              + ', '.join(f'{count}: {value:.3f}' for count, value in result['boost'].items()))
    print(f"Raw units per finger mm: {result['units_per_mm']:.3f} from {result['measured_strokes']} strokes "
          f"(interquartile spread {result['units_spread'] * 100:.1f} %).")
    release, momentum = result['release'], result['momentum']
    if release:
        print(f"Release: mean of the last {release['release_ms']} ms × {release['release_gain']:.3f} "
              f"({release['flicks']} flicks, log spread {release['spread']:.3f}); momentum starts above "
              f"{release['release_min']:.0f} units/s{'' if release['separable'] else ' (overlaps stopped strokes)'}.")
    if momentum:
        mode = f"{momentum['momentum_table_hz']} Hz table" if momentum['momentum_table_hz'] else 'direct frames'
        print(f"Momentum at {momentum['rate_hz']:.1f} Hz, {mode}: median distance error {momentum['error'] * 100:.1f} % "
              f"over {momentum['sequences']} glides (duration ×{momentum['duration_ratio']:.2f}); decay "
              f"{momentum['decay']['decay_fast']}→{momentum['decay']['decay_slow']}. "
              f"Direct {momentum['modes'][0] * 100:.1f} %, table {momentum['modes'][60] * 100:.1f} %.")
    if result['interruption_ms']:
        print(f"A landing finger stops momentum after {statistics.median(result['interruption_ms']):.0f} ms "
              f"(median of {len(result['interruption_ms'])}).")
    checks = [
        (result['events'] >= MIN_EVENTS and result['median_error'] <= 1, 'accelerator ≤1 %'),
        (result['measured_strokes'] >= MIN_STROKES and result['units_spread'] <= 0.1, 'finger mapping within ±10 %'),
        (bool(release) and release['flicks'] >= MIN_FLICKS, f'≥{MIN_FLICKS} flicks'),
        (bool(momentum) and momentum['error'] <= 0.05, 'momentum within 5 %'),
        (result['driver'] is not None, 'every constant measured'),
    ]
    passed = all(ok for ok, _ in checks)
    print(f"\n{'PASS' if passed else 'FAIL'}: " + '; '.join(f"{label} {'✓' if ok else '✗'}" for ok, label in checks))
    summary = (f"scroll probe: accelerator median error {result['median_error']:.2f} %, momentum "
               f"{momentum['error'] * 100:.1f} % over {momentum['sequences']} glides") if momentum else ''
    return passed, summary
