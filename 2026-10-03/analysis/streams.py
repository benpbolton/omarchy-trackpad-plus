from pathlib import Path
import copy, math, statistics as st, sys
sys.path[:0] = ['.', 'tools/macos']
import pointer_profiles as pp, scroll_profiles as sp, scroll_check as c
profile = pp.load_profile(open(Path(__file__).resolve().parent.parent / 'profile-after-check.json', 'rb').read())
rows = c.read_recording(sys.argv[1])['scroll']
f = sp.scroll_function(profile); sc = profile['scroll']
new = lambda: sp.ScrollAccelerator(f, sc['resolution'], sc['report_rate_hz'])

def run(name, route):
    """route(axis_state, row_time) -> (accelerator to use, keep history?)"""
    errs = {'contact': [], 'momentum': []}
    state = {n: {'a': new(), 'b': new(), 'last': None, 'i': 0} for n in 'xy'}
    for r in rows:
        if not math.isfinite(r['hid_time']): continue
        mom = r['hid_momentum'] > 0
        for n in 'xy':
            raw, act = r[f'hid_raw_{n}'], r[f'hid_accel_{n}']
            if not math.isfinite(raw) or not raw: continue
            s = state[n]
            acc, keep = (s['a'], True) if mom else route(s, r['hid_time'])
            if not keep:
                trial = copy.deepcopy(acc); p = trial.accelerate(raw, r['hid_time'])
            else:
                p = acc.accelerate(raw, r['hid_time'], 120.0 if mom else None)
            s['last'] = r['hid_time']; s['i'] += 1
            if math.isfinite(act) and abs(act) > 1e-6:
                errs['momentum' if mom else 'contact'].append(abs(p / act - 1) * 100)
    all_ = errs['contact'] + errs['momentum']
    print(f"{name:44s} median {st.median(all_):6.2f}%  contact {st.median(errs['contact']):6.2f}%  momentum {st.median(errs['momentum']):6.2f}%")

run('one history (port) + momentum at 120 Hz', lambda s, t: (s['a'], True))
run('strict alternation A/B', lambda s, t: (s['a'] if s['i'] % 2 == 0 else s['b'], True))
for ms in (2.0, 2.5, 3.0, 3.5, 4.5):
    run(f'gap < {ms} ms -> second history', lambda s, t, ms=ms: (s['b'] if s['last'] and (t - s['last']) * 1000 < ms else s['a'], True))
for ms in (2.5, 3.5):
    run(f'gap < {ms} ms -> not kept in history', lambda s, t, ms=ms: (s['a'], not (s['last'] and (t - s['last']) * 1000 < ms)))
