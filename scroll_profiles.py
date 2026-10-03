#!/usr/bin/env python3
"""macOS two-finger scrolling: Apple's scroll accelerator, its momentum, and libinput points.

macOS scrolls a trackpad in three stages; tools/macos/README.md links the source of each.

1. The closed multitouch driver turns two-finger motion into raw scroll deltas and, after
   the fingers lift, generates momentum deltas. A profile's scroll `driver` holds the
   constants the scroll check measures for it.
2. IOHIDScrollAccelerator (IOHIDFamily) accelerates every non-zero delta, momentum included,
   from the average of up to nine recent events on that axis. ScrollAccelerator ports it
   line by line.
3. WindowServer and AppKit turn the accelerated value into points (`points_per_unit`).

Momentum follows the system decay that WebKit's MomentumEventDispatcher reproduces. libinput
can neither keep history nor generate momentum, so convert() samples the steady state.
Stdlib only; shared by trackpads.py and tools/macos/.
"""
import math

import pointer_profiles as pp

AVERAGE_LENGTH = 9                      # IOHIDAcceleration.hpp: SCROLL_EVENT_AVARAGE_LENGHT
CLEAR_MS = 500.0                        # SCROLL_CLEAR_THRESHOLD_MS
EVENT_MS = 150.0                        # SCROLL_EVENT_THRESHOLD_MS
MULTIPLIER_A = 0x00000002 / pp.FIXED    # SCROLL_MULTIPLIER_A
MULTIPLIER_B = 0x000003bb / pp.FIXED    # SCROLL_MULTIPLIER_B
MULTIPLIER_C = 0x00018041 / pp.FIXED    # SCROLL_MULTIPLIER_C
PIXEL_TO_WHEEL = 0x0000199a / pp.FIXED  # SCROLL_PIXEL_TO_WHEEL_SCALE
DEFAULT_DISPATCH_RATE = 60.0            # IOHIDPointerScrollFilter.h: kIOHIDDefaultReportRate
DECAY_PERIOD = 0.008                    # WebKit momentumDecayRate: alpha applies per 8 ms
# WebKit MomentumEventDispatcher.cpp (defaultDecay, tailDecay, tailVelocity, and the 0.5 per
# 60 Hz frame at which its table ends); the scroll check verifies them on the Mac.
DECAY = {'decay_fast': 0.975, 'decay_slow': 0.91, 'decay_velocity': 250.0, 'stop_velocity': 30.0}
ERROR_BANDS = ((3, 10), (10, 30), (30, 300), (300, 800))  # finger speed, mm/s
PLOT_SPEEDS = [1] + list(range(10, 410, 10))  # finger speed, mm/s


def scroll_function(profile):
    """Apple's curve at the profile's scroll speed, from HIDScrollAccelCurves."""
    scroll = profile['scroll']
    return pp.apple_function(pp.curve_parameters(scroll['curves'], scroll['speed']))


def velocity_scale(average_ms):
    """IOHIDScrollAccelerator: velocity per unit of average delta at an average event interval."""
    return MULTIPLIER_A * average_ms * average_ms - MULTIPLIER_B * average_ms + MULTIPLIER_C


class ScrollAccelerator:
    """One axis of IOHIDScrollAccelerator::accelerate with IOHIDParametricAcceleration.

    `rate` is HIDScrollReportRate (67, Apple's FRAME_RATE, when the device has none); it sets
    both the curve's device scale and the accelerator's rate multiplier.
    """

    def __init__(self, f, resolution, rate):
        self.f, self.resolution, self.rate = f, resolution, rate
        self.events = [(0.0, 0.0)] * AVERAGE_LENGTH  # (ms since this axis's previous delta, |delta|)
        self.head = self.tail = 0
        self.direction = None
        self.last = None

    def multiplier(self, velocity):
        return self.f(velocity * self.rate / self.resolution) * pp.CURSOR_SCALE

    def accelerate(self, scroll, seconds, dispatch_rate=None):
        """Accelerate one non-zero raw delta received at `seconds`.

        IOHIDPointerScrollFilter skips zero deltas, so they never reach the history. A momentum
        event dispatched at `dispatch_rate` Hz is scaled to 60 Hz around the call, as the filter
        does with the event's ScrollMomentumDispatchRate.
        """
        scale = dispatch_rate / DEFAULT_DISPATCH_RATE if dispatch_rate else 1.0
        scroll *= scale
        # A first event, or a clock that runs backwards, wraps the unsigned difference.
        delta_ms = (seconds - self.last) * 1000 if self.last is not None and seconds >= self.last else math.inf
        self.last = seconds
        head = self.head
        self.events[head] = (delta_ms, abs(scroll))
        self.head = (self.head + 1) % AVERAGE_LENGTH
        if self.head == self.tail:
            self.tail = (self.tail + 1) % AVERAGE_LENGTH
        direction = scroll > 0
        if self.direction != direction or delta_ms > CLEAR_MS:
            self.tail = head
            self.direction = direction
        total_ms, total, count, index = 0.0, 0.0, 0, self.head
        while True:  # newest first, as Apple's do … while (i != _tail)
            index = (index or AVERAGE_LENGTH) - 1
            gap, size = self.events[index]
            total += size
            count += 1
            if gap > EVENT_MS:
                total_ms += EVENT_MS
                break
            total_ms += gap
            if total_ms >= CLEAR_MS or index == self.tail:
                break
        rate_multiplier = self.rate / pp.FRAME_RATE
        average_ms = min(max(total_ms / count * rate_multiplier, 1), EVENT_MS)
        velocity = max(velocity_scale(average_ms) * total / count * rate_multiplier, pp.MINIMUM_VELOCITY)
        return scroll * self.multiplier(velocity) / velocity * PIXEL_TO_WHEEL / scale


def accelerators(profile):
    scroll = profile['scroll']
    f = scroll_function(profile)
    return ScrollAccelerator(f, scroll['resolution'], scroll['report_rate_hz']), \
        ScrollAccelerator(f, scroll['resolution'], scroll['report_rate_hz'])


def constants(driver):
    return {key: driver[key] for key in DECAY} if driver else dict(DECAY)


def momentum(velocity, rate, decay=DECAY, table_rate=0):
    """Raw momentum deltas per frame at `rate` Hz, from a release velocity in raw units/s.

    WebKit's computeNextDelta: the first frame carries the release delta; every later frame
    decays by alpha^(frame / 8 ms), alpha blending from decay_fast to decay_slow as the
    diagonal speed falls below decay_velocity. It ends with the first frame whose axes are
    both at or below stop_velocity.

    With `table_rate` (WebKit uses 60 Hz), the curve is built at that rate and its cumulative
    offset is sampled at `rate`, which keeps the distance of the table rate; generating at
    `rate` directly glides about λ·Δt/2 less at higher rates. The scroll check measures which
    one macOS uses (`momentum_table_hz`, 0 for direct).
    """
    if table_rate and table_rate != rate:
        table = momentum(velocity, table_rate, decay)
        offsets, x, y = [(0.0, 0.0)], 0.0, 0.0
        for dx, dy in table:
            x, y = x + dx, y + dy
            offsets.append((x, y))

        def offset(seconds):
            position = min(seconds * table_rate, len(table))
            index = min(int(position), len(table) - 1)
            part = position - index
            (x0, y0), (x1, y1) = offsets[index], offsets[index + 1]
            return x0 + (x1 - x0) * part, y0 + (y1 - y0) * part

        frames = math.ceil(len(table) * rate / table_rate)
        samples = [offset(k / rate) for k in range(frames + 1)]
        return [(b[0] - a[0], b[1] - a[1]) for a, b in zip(samples, samples[1:])]
    vx, vy = velocity
    period = 1 / rate
    frames = [(vx * period, vy * period)]
    while len(frames) < 100000:
        speed = math.hypot(vx, vy)
        weak = max(0.0, (decay['decay_velocity'] - speed) / decay['decay_velocity'])
        alpha = decay['decay_fast'] - (decay['decay_fast'] - decay['decay_slow']) * weak
        factor = alpha ** (period / DECAY_PERIOD)
        vx, vy = vx * factor, vy * factor
        frames.append((vx * period, vy * period))
        if abs(vx) <= decay['stop_velocity'] and abs(vy) <= decay['stop_velocity']:
            break
    return frames


def release_velocity(contact, driver):
    """Raw units/s over the last `release_ms` of contact deltas [(seconds, dx, dy)]."""
    if not contact:
        return 0.0, 0.0
    window = driver['release_ms'] / 1000
    end = contact[-1][0]
    recent = [(dx, dy) for seconds, dx, dy in contact if seconds > end - window]
    gain = driver['release_gain'] / window
    return sum(d[0] for d in recent) * gain, sum(d[1] for d in recent) * gain


def simulate(profile, contact, lift=None):
    """Accelerate a stroke as macOS would: contact deltas, then momentum if it starts.

    `contact` is [(seconds, dx, dy)] of raw driver deltas; `lift` is when the fingers left
    (default: one event period after the last delta). Returns [(seconds, ax, ay, momentum)]
    in accelerated scroll units; multiply by `points_per_unit` for points.
    """
    scroll = profile['scroll']
    driver = scroll['driver']
    x_axis, y_axis = accelerators(profile)
    out = []

    def push(seconds, dx, dy, rate, is_momentum):
        ax = x_axis.accelerate(dx, seconds, rate) if dx else 0.0
        ay = y_axis.accelerate(dy, seconds, rate) if dy else 0.0
        out.append((seconds, ax, ay, is_momentum))

    for seconds, dx, dy in contact:
        push(seconds, dx, dy, None, False)
    if not contact:
        return out
    vx, vy = release_velocity(contact, driver)
    if math.hypot(vx, vy) < driver['release_min']:
        return out
    rate = scroll['momentum_rate_hz']
    start = lift if lift is not None else contact[-1][0] + 1 / driver['event_rate_hz']
    frames = momentum((vx, vy), rate, constants(driver), driver['momentum_table_hz'])
    for index, (dx, dy) in enumerate(frames):
        if dx or dy:
            push(start + index / rate, dx, dy, rate, True)
    return out


def steady_points(profile, finger_mm_s):
    """Points per second for a steady two-finger stroke, with the accelerator's history full."""
    scroll = profile['scroll']
    driver = scroll['driver']
    f = scroll_function(profile)
    rate = scroll['report_rate_hz']
    per_event = driver['units_per_mm'] * finger_mm_s / driver['event_rate_hz']
    if per_event <= 0:
        return 0.0
    rate_multiplier = rate / pp.FRAME_RATE
    average_ms = min(max(1000 / driver['event_rate_hz'] * rate_multiplier, 1), EVENT_MS)
    velocity = max(velocity_scale(average_ms) * per_event * rate_multiplier, pp.MINIMUM_VELOCITY)
    accelerated = per_event * f(velocity * rate / scroll['resolution']) * pp.CURSOR_SCALE / velocity
    return accelerated * PIXEL_TO_WHEEL * driver['points_per_unit'] * driver['event_rate_hz']


def convert(profile, units_per_mm, scale):
    """Sample the steady-state scroll curve as libinput `scroll_points` for one interface.

    libinput's input is raw trackpad units per ms (x resolution) and its output is logical px
    per ms, which Hyprland sends as axis values with scroll_factor 1. `scale` is logical px per
    macOS point (pointer_profiles.px_per_point). Where Apple's curve turns linear, the last two
    points sit on that line so libinput's extrapolation stays exact up to the root knee.
    """
    scroll = profile.get('scroll')
    if not scroll or not scroll['driver']:
        raise ValueError('This profile has no measured scrolling; run the scroll check on the Mac')
    pp.number(units_per_mm, 1, 10000)
    pp.number(scale, 0.01, 100)
    driver = scroll['driver']
    parameters = pp.curve_parameters(scroll['curves'], scroll['speed'])
    mm_per_unit = 1000 / units_per_mm  # finger mm/s per libinput unit/ms

    def output(speed):
        return steady_points(profile, speed * mm_per_unit) * scale / 1000

    limit = 1200 / mm_per_unit  # sample no further than a 1.2 m/s flick
    if parameters['tangent_linear']:
        rate_multiplier = scroll['report_rate_hz'] / pp.FRAME_RATE
        average_ms = min(max(1000 / driver['event_rate_hz'] * rate_multiplier, 1), EVENT_MS)
        velocity = parameters['tangent_linear'] * scroll['resolution'] / scroll['report_rate_hz']
        per_event = velocity / (velocity_scale(average_ms) * rate_multiplier)
        limit = min(limit, per_event * driver['event_rate_hz'] / driver['units_per_mm'] / mm_per_unit)
    else:
        limit = min(limit, 800 / mm_per_unit)
    step = math.ceil(limit / (pp.NPOINTS - 2) * 10000) / 10000
    points = [round(output(index * step), 6) for index in range(pp.NPOINTS)]
    if not 0 < step <= pp.LIBINPUT_LIMIT or points[-1] > pp.LIBINPUT_LIMIT:
        raise ValueError('This profile does not fit libinput’s custom scroll range')
    px_per_mm = scale / pp.mm_per_point(profile)
    bands = {}
    for low, high in ERROR_BANDS:
        worst, speed = 0.0, low
        while speed <= high:
            units = speed / mm_per_unit
            expected = output(units)
            if expected:
                worst = max(worst, abs(pp.interpolate(step, points, units) / expected - 1) * 100)
            speed *= 1.02
        bands[f'{low:g}-{high:g}'] = round(worst, 2)
    plot = [[speed, round(pp.interpolate(step, points, speed / mm_per_unit) / px_per_mm * 1000 / speed, 4)]
            for speed in PLOT_SPEEDS]
    return {'step': step, 'points': points, 'px_per_point': round(scale, 6), 'plot': plot,
            'error_bands': bands, 'native': f'{step:.4f} ' + ' '.join(f'{point:.6f}' for point in points)}
