#!/usr/bin/env python3
"""macOS pointer profiles: validation, Apple's acceleration curve, and libinput points.

A profile records the acceleration curves and tracking speed a Mac exposes in `ioreg`, so
the same transfer function can be rebuilt for libinput. Version 2 adds the scroll curves that
scroll_profiles.py models. Shared by trackpads.py and tools/macos/export-profile.py;
tools/macos/README.md cites the source of every constant.
"""
import hashlib
import json
import math

FORMAT = 'trackpad-plus/pointer-profile'
MAX_PROFILE_BYTES = 64 * 1024
FIXED = 65536  # IOHIDFamily stores curve parameters as 16.16 fixed point.
FRAME_RATE = 67.0  # IOHIDAcceleration.hpp: speeds are standardised to 67 events per second.
CURSOR_SCALE = 96.0 / 67.0  # IOHIDAccelerationAlgorithm.hpp: kCursorScale.
MINIMUM_VELOCITY = 1 / FIXED  # IOHIDAcceleration.cpp: FIXED_TO_DOUBLE(0x1).
NPOINTS = 64  # libinput-private.h: LIBINPUT_ACCEL_NPOINTS_MAX.
LIBINPUT_LIMIT = 10000  # LIBINPUT_ACCEL_STEP_MAX and LIBINPUT_ACCEL_POINT_MAX_VALUE.
CURVE_KEYS = ('index', 'linear', 'parabolic', 'cubic', 'quartic', 'tangent_linear', 'tangent_root')
PROFILE_KEYS = {'format', 'version', 'kind', 'name', 'tracking_speed', 'curves', 'driver', 'display', 'source'}
DRIVER_KEYS = {'resolution_dpi', 'report_rate_hz', 'event_rate_hz', 'counts_per_inch', 'deltas', 'verified'}
DISPLAY_KEYS = {'points_wide', 'pixels_wide', 'width_mm'}
# Version 2 adds two-finger scrolling (scroll_profiles.py). `driver` stays null until the
# scroll check has measured the closed multitouch driver's constants.
SCROLL_KEYS = {'speed', 'curves', 'resolution', 'report_rate_hz', 'momentum_rate_hz', 'natural', 'driver'}
SCROLL_DRIVER_RANGES = {
    'units_per_mm': (0.01, 1000),      # raw scroll units per mm of two-finger travel
    'event_rate_hz': (30, 1000),       # scroll events per second while fingers move
    'points_per_unit': (0.01, 1000),   # points of scrolling per accelerated scroll unit
    'release_ms': (1, 500),            # contact history that sets the first momentum delta
    'release_gain': (0.01, 100),       # first momentum delta ÷ that history's mean delta
    'release_min': (0, 100000),        # slowest release (raw units/s) that starts momentum
    'decay_fast': (0.5, 1),            # momentum decay per 8 ms at and above decay_velocity
    'decay_slow': (0.5, 1),            # … blending to this as momentum approaches rest
    'decay_velocity': (1, 100000),     # raw units/s
    'stop_velocity': (0, 100000),      # raw units/s per axis at which momentum ends
    'momentum_table_hz': (0, 1000),    # rate the momentum curve is built at; 0: each frame directly
}
DELTA_MODELS = ('ideal', 'integer', 'fractional')
ERROR_BANDS = ((1.5, 3), (3, 6), (6, 600), (600, 800), (800, 1200))  # finger speed, mm/s
PLOT_SPEEDS = [1] + list(range(10, 410, 10))  # finger speed, mm/s


def number(value, low, high, integer=False):
    if type(value) not in ((int,) if integer else (int, float)) or not math.isfinite(value) \
            or not low <= value <= high:
        raise ValueError('Pointer profile value is outside its allowed range')
    return value


def text(value, limit, empty=False):
    if not isinstance(value, str) or len(value) > limit or not (empty or value) or not value.isprintable():
        raise ValueError('Pointer profile text is missing, too long, or not printable')
    return value


def validate_curves(curves):
    """HIDAccelCurves or HIDScrollAccelCurves, as raw 16.16 integers in the device's order."""
    if not isinstance(curves, list) or not 1 <= len(curves) <= 16:
        raise ValueError('Expected 1 to 16 acceleration curves')
    previous = -1
    for curve in curves:
        if not isinstance(curve, dict) or set(curve) != set(CURVE_KEYS):
            raise ValueError('Invalid acceleration curve')
        for key in CURVE_KEYS:
            number(curve[key], 0, 1000 * FIXED, integer=True)
        if curve['index'] <= previous:
            raise ValueError('Acceleration curves must be sorted by unique index')
        previous = curve['index']
        # IOHIDFamily skips gainless curves, which would shift its index lookup; reject them.
        if not any(curve[key] for key in ('linear', 'parabolic', 'cubic', 'quartic')):
            raise ValueError('Acceleration curve has no gain')
        if curve['tangent_linear'] and curve['tangent_root'] and curve['tangent_root'] <= curve['tangent_linear']:
            raise ValueError('Acceleration curve tangents are out of order')
    return curves


def validate_scroll(scroll):
    if not isinstance(scroll, dict) or set(scroll) != SCROLL_KEYS:
        raise ValueError('Invalid pointer profile scrolling')
    number(scroll['speed'], 0, 10)
    validate_curves(scroll['curves'])
    # Literal 16.16 readings, even implausible ones: the scroll check proves the interpretation.
    number(scroll['resolution'], 0.0001, 20000)
    number(scroll['report_rate_hz'], 0.0001, 1000)
    number(scroll['momentum_rate_hz'], 1, 1000)
    if type(scroll['natural']) is not bool:
        raise ValueError('Invalid pointer profile scrolling')
    driver = scroll['driver']
    if driver is None:
        return scroll
    if not isinstance(driver, dict) or set(driver) != set(SCROLL_DRIVER_RANGES) | {'verified'}:
        raise ValueError('Invalid pointer profile scroll constants')
    for key, (low, high) in SCROLL_DRIVER_RANGES.items():
        number(driver[key], low, high)
    if driver['decay_slow'] > driver['decay_fast']:
        raise ValueError('Pointer profile momentum decay is out of order')
    text(driver['verified'], 160, empty=True)
    return scroll


def validate_profile(value):
    if not isinstance(value, dict) or not PROFILE_KEYS <= set(value) <= PROFILE_KEYS | {'scroll'}:
        raise ValueError('Not a Trackpad Plus pointer profile')
    if value['format'] != FORMAT or type(value['version']) is not int or value['version'] not in (1, 2):
        raise ValueError('Unsupported pointer profile format or version')
    if ('scroll' in value) != (value['version'] == 2):
        raise ValueError('Only version 2 pointer profiles describe scrolling')
    if value['kind'] != 'apple-parametric':
        raise ValueError('Unsupported pointer profile kind')
    text(value['name'], 80)
    number(value['tracking_speed'], 0, 3)
    validate_curves(value['curves'])
    if value['version'] == 2:
        validate_scroll(value['scroll'])
    driver = value['driver']
    if not isinstance(driver, dict) or set(driver) != DRIVER_KEYS:
        raise ValueError('Invalid pointer profile driver constants')
    for key, low, high in [('resolution_dpi', 50, 5000), ('report_rate_hz', 30, 1000),
                           ('event_rate_hz', 30, 1000), ('counts_per_inch', 50, 5000)]:
        number(driver[key], low, high)
    if driver['deltas'] not in DELTA_MODELS:
        raise ValueError('Unknown pointer profile delta model')
    text(driver['verified'], 160, empty=True)
    display = value['display']
    if not isinstance(display, dict) or set(display) != DISPLAY_KEYS:
        raise ValueError('Invalid pointer profile display')
    number(display['points_wide'], 100, 20000)
    number(display['pixels_wide'], 100, 20000, integer=True)
    number(display['width_mm'], 20, 2000)
    source = value['source']
    if not isinstance(source, dict) or len(source) > 16:
        raise ValueError('Invalid pointer profile source')
    for key, item in source.items():
        text(key, 40)
        if isinstance(item, str):
            text(item, 160, empty=True)
        else:
            number(item, -1e9, 1e9)
    return value


def reject_constant(name):
    raise ValueError(f'Pointer profiles must not contain {name}')


def load_profile(raw):
    """Parse untrusted bytes; NaN and Infinity are rejected before validation."""
    if len(raw) > MAX_PROFILE_BYTES:
        raise ValueError('Pointer profile exceeds the 64 KiB limit')
    return validate_profile(json.loads(raw.decode('utf-8'), parse_constant=reject_constant))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def apple_parameters(profile):
    return curve_parameters(profile['curves'], profile['tracking_speed'])


def curve_parameters(curves, speed):
    """Mirror IOHIDParametricAcceleration::CreateWithParameters: linear in every parameter."""
    rows = [{key: curve[key] / FIXED for key in CURVE_KEYS} for curve in curves]
    current = 0
    for position, row in enumerate(rows):
        if speed >= row['index']:
            current = position
    low = rows[current]
    if low['index'] < speed and current + 1 < len(rows):
        high = rows[current + 1]
        ratio = (speed - low['index']) / (high['index'] - low['index'])
        return {key: low[key] + ratio * (high[key] - low[key]) for key in CURVE_KEYS}
    return dict(low)


def apple_function(parameters):
    """Apple's three-segment curve, without kCursorScale (IOHIDParametricAcceleration::multiplier)."""
    p = parameters
    linear, root = p['tangent_linear'], p['tangent_root']

    def poly(x):  # Apple raises gain and speed together: (g·x)ⁿ, not g·xⁿ.
        return p['linear'] * x + (p['parabolic'] * x) ** 2 + (p['cubic'] * x) ** 3 + (p['quartic'] * x) ** 4

    def slope(x):
        return (p['linear'] + 2 * x * p['parabolic'] ** 2 + 3 * x ** 2 * p['cubic'] ** 3
                + 4 * x ** 3 * p['quartic'] ** 4)

    tangent, m, b = [math.inf, math.inf], [0.0, 0.0], [0.0, 0.0]
    if linear:
        m[0] = slope(linear)
        b[0] = poly(linear) - m[0] * linear
        tangent[0] = linear
        if root:
            y1 = m[0] * root + b[0]
            m[1] = 2 * y1 * m[0]
            b[1] = y1 ** 2 - m[1] * root
            tangent[1] = root
    elif root:
        m[1] = slope(root)
        b[1] = poly(root) ** 2 - m[1] * root
        tangent[0] = root

    def f(x):
        if x <= tangent[0]:
            return poly(x)
        if x <= tangent[1] and tangent[0] == linear:
            return m[0] * x + b[0]
        return math.sqrt(m[1] * x + b[1])
    return f


def apple_multiplier(f, velocity, driver):
    """Points for one event of `velocity` counts (IOHIDParametricAcceleration::multiplier)."""
    return f(velocity * FRAME_RATE / driver['resolution_dpi']) * CURSOR_SCALE


def apple_event(f, dx, dy, dt_ms, driver):
    """Accelerate one event of raw counts, as IOHIDPointerAccelerator::accelerate does."""
    rate_multiplier = 1.0
    if dt_ms:
        period = 1000 / driver['report_rate_hz']
        rate_multiplier = period / max(dt_ms, period)
    velocity = max(math.floor(math.hypot(dx, dy)) * rate_multiplier, MINIMUM_VELOCITY)
    scale = apple_multiplier(f, velocity, driver) / velocity
    return dx * scale, dy * scale


def floor_gain(f, whole, driver):
    """Points per count for an event whose |Δ| floors to `whole` counts."""
    velocity = max(whole, MINIMUM_VELOCITY)
    return apple_multiplier(f, velocity, driver) / velocity


def cursor_speed(f, finger_in_s, driver):
    """Cursor points/s for a steady finger speed in inches/s.

    `deltas` describes the closed multitouch driver: ideal (continuous counts), integer
    (whole counts with carried remainders), or fractional, where Apple's per-event floor makes
    a sawtooth; a stroke's per-event counts vary, so that case averages over one count.
    """
    rate = driver['event_rate_hz']
    counts = driver['counts_per_inch'] * finger_in_s / rate
    if driver['deltas'] == 'fractional':
        low, high, total = counts - 0.5, counts + 0.5, 0.0
        whole = math.floor(low)
        while whole < high:
            a, b = max(low, whole), min(high, whole + 1)
            total += floor_gain(f, max(whole, 0), driver) * (b * b - a * a) / 2
            whole += 1
        return rate * total
    if driver['deltas'] == 'integer' and counts >= 1:
        whole = math.floor(counts)
        part = counts - whole
        return rate * ((1 - part) * apple_multiplier(f, whole, driver)
                       + part * apple_multiplier(f, whole + 1, driver))
    return rate * apple_multiplier(f, counts, driver)


def mm_per_point(profile):
    display = profile['display']
    return display['width_mm'] / display['points_wide']


def px_per_point(millimetres, monitor):
    """Logical px per macOS point that keeps the cursor's physical travel on a Hyprland monitor."""
    for key in ('width', 'scale', 'physicalWidth'):
        number(monitor.get(key), 1e-6, 1e6)
    return millimetres * monitor['width'] / monitor['scale'] / monitor['physicalWidth']


def interpolate(step, points, speed):
    """libinput's custom profile: linear between points, extrapolated from the last two."""
    index = min(int(speed / step), len(points) - 2)
    return points[index] + (points[index + 1] - points[index]) * (speed / step - index)


def convert(profile, units_per_mm, scale):
    """Sample a profile as libinput custom points for one trackpad interface.

    libinput's input is raw trackpad units per ms at the x resolution and its output is
    logical px per ms; `scale` is logical px per macOS point (see px_per_point). The last two
    points sit on Apple's tangent line, so libinput's linear extrapolation stays exact up to
    the square-root knee.
    """
    number(units_per_mm, 1, 10000)
    number(scale, 0.01, 100)
    parameters = apple_parameters(profile)
    f = apple_function(parameters)
    driver = profile['driver']
    inches = 1000 / (units_per_mm * 25.4)  # finger inches/s per libinput unit/ms

    def output(speed):
        return cursor_speed(f, speed * inches, driver) * scale / 1000

    if parameters['tangent_linear']:
        counts = parameters['tangent_linear'] * driver['resolution_dpi'] / FRAME_RATE
        linear_from = counts * driver['event_rate_hz'] / driver['counts_per_inch'] / inches
        step = math.ceil(linear_from / (NPOINTS - 2) * 10000) / 10000
    else:
        step = math.ceil(600 / 25.4 / inches / (NPOINTS - 1) * 10000) / 10000
    points = [round(output(index * step), 6) for index in range(NPOINTS)]
    if not 0 < step <= LIBINPUT_LIMIT or points[-1] > LIBINPUT_LIMIT:
        raise ValueError('This profile does not fit libinput’s custom acceleration range')
    px_per_mm = scale / mm_per_point(profile)
    bands = {}
    for low, high in ERROR_BANDS:
        worst = 0.0
        speed = low
        while speed <= high:
            actual = interpolate(step, points, speed * units_per_mm / 1000)
            expected = output(speed * units_per_mm / 1000)
            worst = max(worst, abs(actual / expected - 1) * 100)
            speed *= 1.02
        bands[f'{low:g}-{high:g}'] = round(worst, 2)
    plot = [[speed, round(interpolate(step, points, speed * units_per_mm / 1000) / px_per_mm * 1000 / speed, 4)]
            for speed in PLOT_SPEEDS]
    return {'step': step, 'points': points, 'px_per_point': round(scale, 6), 'plot': plot,
            'error_bands': bands,
            'native': f'custom {step:.4f} ' + ' '.join(f'{point:.6f}' for point in points)}
