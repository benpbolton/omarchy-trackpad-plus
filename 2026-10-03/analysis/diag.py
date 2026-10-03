from pathlib import Path
import json, math, statistics as st, sys
sys.path[:0] = ['.', 'tools/macos']
import pointer_profiles as pp, scroll_profiles as sp, scroll_check as c
profile = pp.load_profile(open(Path(__file__).resolve().parent.parent / 'profile-after-check.json', 'rb').read())
rec = c.read_recording(sys.argv[1])
rows = rec['scroll']

def replay(trial, rows, use_rate=True):
    xa, ya = sp.accelerators(trial)
    out = []
    for row in rows:
        if not math.isfinite(row['hid_time']): continue
        mom = row['hid_momentum'] > 0 if math.isfinite(row['hid_momentum']) else bool(row['momentum_phase'])
        rate = row['hid_dispatch_rate'] if use_rate and mom and math.isfinite(row['hid_dispatch_rate']) else None
        for n, a in (('x', xa), ('y', ya)):
            raw, act = row[f'hid_raw_{n}'], row[f'hid_accel_{n}']
            if not math.isfinite(raw) or not raw: continue
            p = a.accelerate(raw, row['hid_time'], rate)
            if math.isfinite(act) and abs(act) > 1e-6:
                out.append(dict(ratio=p / act, mom=mom, raw=raw, act=act, rate=row['hid_dispatch_rate'], axis=n, t=row['hid_time']))
    return out

def summary(name, out):
    r = [o['ratio'] for o in out]
    e = sorted(abs(x - 1) * 100 for x in r)
    q = st.quantiles(r, n=4)
    print(f"{name:28s} n={len(r):5d} median err {e[len(e)//2]:6.2f}%  ratio p25/50/75 {q[0]:.4f} {q[1]:.4f} {q[2]:.4f}")

out = replay(profile, rows)
summary('as exported', out)
summary('  contact only', [o for o in out if not o['mom']])
summary('  momentum only', [o for o in out if o['mom']])
print('dispatch rates seen on momentum:', sorted({o['rate'] for o in out if o['mom']}))
print('sign mismatches:', sum(o['ratio'] < 0 for o in out))
# ratio vs raw size
for lo, hi in ((0, 2), (2, 5), (5, 10), (10, 20), (20, 50), (50, 1e9)):
    sub = [o for o in out if lo <= abs(o['raw']) < hi and not o['mom']]
    if len(sub) > 5: summary(f'  contact |raw| {lo}-{hi}', sub)
# event spacing
ts = [r['hid_time'] for r in rows if math.isfinite(r['hid_time'])]
gaps = sorted((b - a) * 1000 for a, b in zip(ts, ts[1:]) if b > a)
print('hid event gaps ms p10/50/90:', [round(gaps[int(len(gaps) * q)], 2) for q in (0.1, 0.5, 0.9)])
# raw values whole numbers?
raws = [abs(r['hid_raw_y']) for r in rows if math.isfinite(r['hid_raw_y']) and r['hid_raw_y']]
print('raw y whole numbers:', sum(x == int(x) for x in raws), 'of', len(raws), ' sample', raws[:12])
