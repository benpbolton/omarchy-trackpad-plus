"""Check a scroll-probe.swift recording against macOS and measure the scroll constants.

1. Apple's IOHIDScrollAccelerator is open source, so it must reproduce every momentum value
   once a glide's history holds only momentum, and every stroke's first event, which has no
   history. Contact events in between cannot be checked this way: the filter sees the closed
   driver's fractional inputs, and apps receive per-event roundings of two interleaved streams.
2. Apps receive ceil(points_per_unit × accelerated) whole points per event.
3. The finger model is fitted: finger frames (NSTouch) run through scroll_profiles must give
   each stroke's accelerated total. Then the release velocity and the momentum decay.

Used by export-profile.py --check-scroll.
"""
import bisect
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
RELEASE_WINDOWS_MS = (17, 25, 33, 42, 50, 58, 67, 83, 100)
SPLITS = (0.5, 1.0, 1.5, 2.0)
MIN_MOMENTUM, MIN_STARTS, MIN_STROKES, MIN_FLICKS = 200, 5, 10, 8
POINTS_PER_UNIT = 10.0  # the rounding check confirms it
LONE_GAP = 0.6  # seconds without events: Apple's history has been cleared (500 ms)
BANDS = ((0, 10), (10, 40), (40, 160), (160, 400))  # finger mm/s
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


def finite(value):
    return value is not None and math.isfinite(value)


def momentum_rate(rows):
    gaps = [b['hid_time'] - a['hid_time'] for a, b in zip(rows, rows[1:]) if b['hid_time'] > a['hid_time']]
    return 1 / statistics.median(gaps) if gaps else math.nan


def momentum_rows(stroke):
    return [r for r in stroke['momentum'] if finite(r['hid_time']) and finite(r['hid_raw_y'])]


def interrupted(rows):
    return any(finite(r['hid_momentum']) and int(r['hid_momentum']) & INTERRUPTED for r in rows)


def cadence(found):
    """Momentum events per second. The dispatch-rate attachment never reaches apps, so measure it."""
    rates = [momentum_rate(rows) for rows in map(momentum_rows, found) if len(rows) > 5]
    rates = [rate for rate in rates if finite(rate)]
    return round(statistics.median(rates), 1) if rates else math.nan


def dispatch_rate(row, measured):
    return row['hid_dispatch_rate'] if finite(row['hid_dispatch_rate']) else measured


def check_accelerator(profile, rows, measured):
    """Errors (%) on momentum events whose history is all momentum, and on stroke starts."""
    x_axis, y_axis = sp.accelerators(profile)
    result = {'momentum': [], 'starts': []}
    glide, last = 0, None
    for row in rows:
        if not finite(row['hid_time']):
            continue
        momentum = row['hid_momentum'] > 0 if finite(row['hid_momentum']) else bool(row['momentum_phase'])
        glide = glide + 1 if momentum else 0
        rate = dispatch_rate(row, measured) if momentum else None
        lone = last is None or row['hid_time'] - last > LONE_GAP
        for name, accelerator in (('x', x_axis), ('y', y_axis)):
            raw, actual = row[f'hid_raw_{name}'], row[f'hid_accel_{name}']
            if not finite(raw) or not raw:
                continue
            predicted = accelerator.accelerate(raw, row['hid_time'], rate)
            last = row['hid_time']
            if finite(actual) and abs(actual) > 1e-6:
                error = abs(predicted / actual - 1) * 100
                if momentum and glide > sp.AVERAGE_LENGTH:
                    result['momentum'].append(error)
                elif lone and not momentum:
                    result['starts'].append(error)
    return {key: sorted(values) for key, values in result.items()}


def check_rounding(rows):
    """Share of events where apps got ceil(POINTS_PER_UNIT × accelerated); repeated swipes excluded."""
    matched = total = 0
    for row in rows:
        if finite(row['scroll_count']) and row['scroll_count'] >= 3:
            continue  # AppKit adds to repeated quick swipes
        for name in ('x', 'y'):
            accelerated, points = row[f'hid_accel_{name}'], row[f'scrolling_d{name}']
            if finite(accelerated) and abs(accelerated) > 1e-6 and finite(points):
                total += 1
                matched += abs(points) == math.ceil(abs(accelerated) * POINTS_PER_UNIT - 1e-9)
    return matched / total if total else math.nan, total


def finger_frames(touches):
    """Two-finger centroid in mm, one row per real frame (NSTouch repeats a frame per finger)."""
    frames = []
    for seconds, touching, width, height, fingers in touches:
        if touching == 2 and len(fingers) == 2 and width > 0 and height > 0:
            x = sum(f[1] for f in fingers) / 2 * width / POINTS_PER_INCH * 25.4
            y = sum(f[2] for f in fingers) / 2 * height / POINTS_PER_INCH * 25.4
            if not frames or (x, y) != frames[-1][1:]:
                frames.append((seconds, x, y))
    return frames


def stroke_motion(found, frames):
    """Per stroke: finger motion frames [(t, dx, dy)] from its first scroll event to its last, and
    Apple's accelerated contact events [(t, ax, ay)], both on the stroke's main axis only.

    Motion before the first event is the driver's start threshold, which libinput replaces with
    its own. The other axis is dropped: the driver suppresses cross-axis jitter, as libinput's
    axis lock does, while NSTouch's centroid keeps it.
    """
    times = [t for t, _, _ in frames]
    data = []
    for stroke in found:
        events = [(r['timestamp'], r['hid_accel_x'] if finite(r['hid_accel_x']) else 0.0,
                   r['hid_accel_y'] if finite(r['hid_accel_y']) else 0.0) for r in stroke['contact']]
        if len(events) < 10:
            continue
        start, end = events[0][0], events[-1][0]
        i0, i1 = bisect.bisect_left(times, start), bisect.bisect_right(times, end)
        if i1 - i0 < 6 or i0 == 0:
            continue
        keep = (0.0, 1.0) if sum(abs(e[2]) for e in events) >= sum(abs(e[1]) for e in events) else (1.0, 0.0)
        motion = [(b[0], (b[1] - a[1]) * keep[0], (b[2] - a[2]) * keep[1])
                  for a, b in zip(frames[i0 - 1:i1 - 1], frames[i0:i1])]
        events = [(e[0], e[1] * keep[0], e[2] * keep[1]) for e in events]
        data.append({'stroke': stroke, 'motion': motion, 'apple': events, 'axis': 'y' if keep[1] else 'x'})
    return data


def signs(data):
    """NSTouch's axes against the HID scroll axes (y grows upward on the trackpad)."""
    result = []
    for index in (1, 2):
        dot = sum(sum(e[index] for e in d['apple']) * sum(m[index] for m in d['motion']) for d in data)
        result.append(-1.0 if dot < 0 else 1.0)
    return result


def oriented(motion, sign):
    return [(t, dx * sign[0], dy * sign[1]) for t, dx, dy in motion]


def model_contact(profile, driver, motion):
    x_axis, y_axis = sp.accelerators(profile)
    out = []
    for t, rx, ry in sp.contact_events(motion, driver):
        out.append((t, x_axis.accelerate(rx, t) if rx else 0.0, y_axis.accelerate(ry, t) if ry else 0.0))
    return out


def total_error(profile, driver, data, sign):
    errors = []
    for d in data:
        apple = sum(abs(e[1]) + abs(e[2]) for e in d['apple'])
        if apple < 1:
            continue
        model = sum(abs(e[1]) + abs(e[2]) for e in model_contact(profile, driver, oriented(d['motion'], sign)))
        errors.append(abs(model / apple - 1))
    return statistics.median(errors) if errors else math.inf, len(errors)


def fit_contact(profile, data, frame_rate):
    """units_per_mm and split_min that best reproduce each stroke's accelerated total."""
    if len(data) < 3:
        return None
    sign = signs(data)
    base = {'frame_rate_hz': frame_rate}
    best = None
    for split in SPLITS:
        for units in [8 + 0.5 * i for i in range(33)]:
            error, _ = total_error(profile, dict(base, units_per_mm=units, split_min=split), data, sign)
            if best is None or error < best[0]:
                best = (error, units, split)
    _, coarse, split = best
    for units in [coarse - 0.5 + 0.05 * i for i in range(21)]:
        error, count = total_error(profile, dict(base, units_per_mm=units, split_min=split), data, sign)
        if error <= best[0]:
            best = (error, units, split)
    error, units, split = best
    driver = dict(base, units_per_mm=round(units, 2), split_min=split, points_per_unit=POINTS_PER_UNIT)
    return {'units_per_mm': driver['units_per_mm'], 'split_min': split, 'error': error,
            'strokes': total_error(profile, driver, data, sign)[1], 'sign': sign,
            'bands': app_bands(profile, driver, data, sign)}


def app_bands(profile, driver, data, sign):
    """Model ÷ macOS points that apps receive, by finger speed, over 50 ms windows."""
    ratios = {band: [] for band in BANDS}
    for d in data:
        model = model_contact(profile, driver, oriented(d['motion'], sign))
        rows = d['stroke']['contact']
        motion = d['motion']
        t = d['apple'][0][0] + 0.05
        while t + 0.05 <= d['apple'][-1][0]:
            window = [m for m in motion if t <= m[0] < t + 0.05]
            if len(window) >= 3:
                speed = math.hypot(sum(m[1] for m in window), sum(m[2] for m in window)) / 0.05
                apple = sum(abs(r[f"scrolling_d{d['axis']}"]) for r in rows if t <= r['timestamp'] < t + 0.05)
                ours = sum(abs(sp.points(ax, driver)) + abs(sp.points(ay, driver)) for mt, ax, ay in model if t <= mt < t + 0.05)
                band = next((b for b in BANDS if b[0] <= speed < b[1]), None)
                if band and apple:
                    ratios[band].append(ours / apple)
            t += 0.05
    return {f'{b[0]}-{b[1]}': (statistics.median(v), len(v)) for b, v in ratios.items() if v}


def fit_release(data, units, measured):
    """The finger window and gain that best predict each flick's first momentum velocity."""
    flicks, still = [], []
    for d in data:
        rows = momentum_rows(d['stroke'])
        frames = d['motion']
        if rows and len(rows) > 2:
            rate = dispatch_rate(rows[0], measured)
            flicks.append((frames, (rows[0]['hid_raw_x'] * rate, rows[0]['hid_raw_y'] * rate)))
        elif not d['stroke']['momentum']:
            still.append(frames)
    best = None
    for window in RELEASE_WINDOWS_MS:
        driver = {'release_ms': window, 'release_gain': 1.0, 'units_per_mm': units}
        gains = []
        for frames, first in flicks:
            released = math.hypot(*sp.release_velocity(frames, driver))
            if released > 0 and math.hypot(*first) > 0:
                gains.append(math.hypot(*first) / released)
        if len(gains) < 3:
            continue
        spread = statistics.pstdev(math.log(g) for g in gains)
        if best is None or spread < best[0]:
            best = (spread, window, statistics.median(gains), len(gains))
    if best is None:
        return None
    spread, window, gain, count = best
    driver = {'release_ms': window, 'release_gain': gain, 'units_per_mm': units}
    started = sorted(math.hypot(*sp.release_velocity(f, driver)) for f, _ in flicks)
    stopped = sorted(math.hypot(*sp.release_velocity(f, driver)) for f in still)
    low, high = started[0], max(stopped, default=0.0)
    return {'release_ms': window, 'release_gain': gain, 'flicks': count, 'spread': spread,
            'release_min': (low + high) / 2 if high < low else low, 'separable': high < low}


def momentum_error(rows, decay, table_rate, measured):
    """Distance and duration of a measured glide against the model, as ratios."""
    rate = dispatch_rate(rows[0], measured)
    if not finite(rate):
        return None
    first = (rows[0]['hid_raw_x'] * rate, rows[0]['hid_raw_y'] * rate)
    frames = sp.momentum(first, rate, decay, table_rate)
    measured_distance = sum(math.hypot(r['hid_raw_x'] or 0, r['hid_raw_y'] or 0) for r in rows)
    if not measured_distance:
        return None
    return sum(math.hypot(*f) for f in frames) / measured_distance, len(frames) / len(rows), rate


def fit_momentum(found, measured):
    """Choose the table mode, and refit the decay only if WebKit's constants miss."""
    glides = [rows for rows in map(momentum_rows, found) if len(rows) > 5 and not interrupted(rows)]
    if len(glides) < 3:
        return None

    def score(decay, table_rate):
        results = [r for r in (momentum_error(rows, decay, table_rate, measured) for rows in glides) if r]
        errors = sorted(abs(r[0] - 1) for r in results)
        return (errors[len(errors) // 2] if errors else math.inf), results

    candidates = [(*score(sp.DECAY, mode), mode) for mode in (0, 60)]
    error, results, table_rate = min(candidates, key=lambda c: c[0])
    decay = dict(sp.DECAY)
    if error > 0.03:
        for fast in [0.96 + 0.0025 * i for i in range(11)]:
            for slow in [0.86 + 0.005 * i for i in range(19)]:
                if slow <= fast:
                    trial = dict(sp.DECAY, decay_fast=round(fast, 4), decay_slow=round(slow, 4))
                    trial_error, trial_results = score(trial, table_rate)
                    if trial_error < error:
                        error, decay, results = trial_error, trial, trial_results
    durations = sorted(r[1] for r in results)
    return {'decay': decay, 'momentum_table_hz': table_rate, 'error': error, 'glides': len(results),
            'duration_ratio': durations[len(durations) // 2], 'modes': {c[2]: c[0] for c in candidates}}


def interruption_latency(found, touches):
    """Milliseconds from a finger landing to the end of the momentum it stopped."""
    landings = [seconds for (seconds, touching, *_), (_, before, *_) in zip(touches[1:], touches)
                if touching > before]
    latencies = []
    for stroke in found:
        rows = stroke['momentum']
        if not rows or not interrupted(momentum_rows(stroke)):
            continue
        landed = [t for t in landings if rows[0]['timestamp'] <= t <= rows[-1]['timestamp']]
        if landed:
            latencies.append((rows[-1]['timestamp'] - landed[0]) * 1000)
    return latencies


def view_ratio(recording):
    """How far the scroll view moved per point of AppKit scrolling delta."""
    moved = sum(abs(b[2] - a[2]) + abs(b[1] - a[1]) for a, b in zip(recording['view'], recording['view'][1:]))
    deltas = sum(abs(r['scrolling_dx']) + abs(r['scrolling_dy']) for r in recording['scroll'])
    return moved / deltas if deltas else math.nan


def check_scroll(profile, recording):
    rows = recording['scroll']
    found = strokes(rows)
    measured = cadence(found)
    accelerator = check_accelerator(profile, rows, measured)
    rounding, rounded_events = check_rounding(rows)
    frames = finger_frames(recording['touches'])
    gaps = sorted(b[0] - a[0] for a, b in zip(frames, frames[1:]) if 0 < b[0] - a[0] < 0.02)
    frame_rate = round(1 / gaps[len(gaps) // 2], 1) if gaps else math.nan
    data = stroke_motion(found, frames)
    contact = fit_contact(profile, data, frame_rate) if finite(frame_rate) else None
    release = fit_release(data, contact['units_per_mm'], measured) if contact else None
    momentum = fit_momentum(found, measured)
    median = lambda values: values[len(values) // 2] if values else math.nan
    result = {
        'strokes': len(found), 'momentum_rate_hz': measured, 'frame_rate_hz': frame_rate,
        'momentum_events': len(accelerator['momentum']), 'momentum_accelerator': median(accelerator['momentum']),
        'starts': len(accelerator['starts']), 'start_accelerator': median(accelerator['starts']),
        'rounding': rounding, 'rounded_events': rounded_events, 'contact': contact, 'release': release,
        'momentum': momentum, 'interruption_ms': interruption_latency(found, recording['touches']),
        'view_ratio': view_ratio(recording), 'natural': recording['header'].get('natural', ['?'])[0] == '1',
    }
    result['driver'] = driver_from(result)
    return result


def driver_from(result):
    contact, release, momentum = result['contact'], result['release'], result['momentum']
    if not (contact and release and momentum and finite(result['frame_rate_hz'])):
        return None
    return {'units_per_mm': contact['units_per_mm'], 'frame_rate_hz': result['frame_rate_hz'],
            'split_min': contact['split_min'], 'points_per_unit': POINTS_PER_UNIT,
            'release_ms': release['release_ms'], 'release_gain': round(release['release_gain'], 4),
            'release_min': round(release['release_min'], 2), 'momentum_table_hz': momentum['momentum_table_hz'],
            'verified': '', **{key: momentum['decay'][key] for key in sp.DECAY}}


def report(result):
    """Print the findings; return (passed, summary for the profile)."""
    print(f"{result['strokes']} strokes; finger frames at {result['frame_rate_hz']} Hz; "
          f"momentum at {result['momentum_rate_hz']} Hz.")
    print(f"Apple's scroll accelerator: momentum median error {result['momentum_accelerator']:.3f} % over "
          f"{result['momentum_events']} values; stroke starts {result['start_accelerator']:.3f} % over {result['starts']}.")
    print(f"Points apps receive = ceil({POINTS_PER_UNIT:g} × accelerated) for {result['rounding']:.1%} of "
          f"{result['rounded_events']} events; scroll view moved {result['view_ratio']:.3f} points per AppKit point.")
    contact, release, momentum = result['contact'], result['release'], result['momentum']
    if contact:
        print(f"Finger model: {contact['units_per_mm']} raw units per mm, two events per frame from "
              f"{contact['split_min']} units; stroke totals within {contact['error'] * 100:.1f} % (median of {contact['strokes']}).")
        print('  points apps receive, model ÷ macOS by finger mm/s: '
              + ', '.join(f'{band} {ratio:.2f} ({n})' for band, (ratio, n) in contact['bands'].items()))
    if release:
        print(f"Release: mean finger velocity of the last {release['release_ms']} ms × {release['release_gain']:.3f} "
              f"({release['flicks']} flicks, log spread {release['spread']:.3f}); momentum starts above "
              f"{release['release_min']:.0f} units/s{'' if release['separable'] else ' (overlaps stopped strokes)'}.")
    if momentum:
        mode = f"{momentum['momentum_table_hz']} Hz table" if momentum['momentum_table_hz'] else 'direct frames'
        print(f"Momentum, {mode}: median distance error {momentum['error'] * 100:.1f} % over {momentum['glides']} glides "
              f"(duration ×{momentum['duration_ratio']:.2f}); decay {momentum['decay']['decay_fast']}→"
              f"{momentum['decay']['decay_slow']}. Direct {momentum['modes'][0] * 100:.1f} %, table {momentum['modes'][60] * 100:.1f} %.")
    if result['interruption_ms']:
        print(f"A landing finger stops momentum after {statistics.median(result['interruption_ms']):.0f} ms "
              f"(median of {len(result['interruption_ms'])}).")
    checks = [
        (result['momentum_events'] >= MIN_MOMENTUM and result['momentum_accelerator'] <= 1, 'momentum accelerator ≤1 %'),
        (result['starts'] >= MIN_STARTS and result['start_accelerator'] <= 1, 'stroke starts ≤1 %'),
        (finite(result['rounding']) and result['rounding'] >= 0.9, 'rounding ≥90 %'),
        (bool(contact) and contact['strokes'] >= MIN_STROKES and contact['error'] <= 0.06, 'finger model ≤6 %'),
        (bool(release) and release['flicks'] >= MIN_FLICKS, f'≥{MIN_FLICKS} flicks'),
        (bool(momentum) and momentum['error'] <= 0.05, 'momentum within 5 %'),
        (result['driver'] is not None, 'every constant measured'),
    ]
    passed = all(ok for ok, _ in checks)
    print(f"\n{'PASS' if passed else 'FAIL'}: " + '; '.join(f"{label} {'✓' if ok else '✗'}" for ok, label in checks))
    summary = (f"scroll check: momentum accelerator {result['momentum_accelerator']:.3f} %, finger model "
               f"{contact['error'] * 100:.1f} %, glides {momentum['error'] * 100:.1f} %") if contact and momentum else ''
    return passed, summary
