from pathlib import Path
import json, math, statistics as st, sys
sys.path[:0] = ['.', 'tools/macos']
import pointer_profiles as pp, scroll_profiles as sp, scroll_check as c
profile = pp.load_profile(open(Path(__file__).resolve().parent.parent / 'profile-after-check.json', 'rb').read())
rows = c.read_recording(sys.argv[1])['scroll']

def run(name, change={}, select=lambda r: True, momentum_rate=None, feed=lambda r: True):
    trial = json.loads(json.dumps(profile)); trial['scroll'].update(change)
    xa, ya = sp.accelerators(trial)
    res = {'all': [], 'contact': [], 'momentum': []}
    for r in rows:
        if not math.isfinite(r['hid_time']) or not feed(r): continue
        mom = r['hid_momentum'] > 0
        for n, a in (('x', xa), ('y', ya)):
            raw, act = r[f'hid_raw_{n}'], r[f'hid_accel_{n}']
            if not math.isfinite(raw) or not raw: continue
            p = a.accelerate(raw, r['hid_time'], momentum_rate if mom else None)
            if select(r) and math.isfinite(act) and abs(act) > 1e-6:
                e = abs(p / act - 1) * 100
                res['all'].append(e); res['momentum' if mom else 'contact'].append(e)
    med = lambda v: f"{st.median(v):6.2f}%" if v else '   n/a'
    print(f"{name:40s} n={len(res['all']):5d} median {med(res['all'])}  contact {med(res['contact'])}  momentum {med(res['momentum'])}")

run('as exported')
run('rate plain (4390912)', {'report_rate_hz': 4390912.0})
run('resolution plain (26214400)', {'resolution': 26214400.0})
run('momentum scaled at 120 Hz', momentum_rate=120.0)
run('only rows with 1 child', select=lambda r: r['hid_children'] == 1)
run('only rows with 2 children', select=lambda r: r['hid_children'] == 2)
for rate in (100.0, 120.0, 125.0, 210.0):
    run(f'report rate {rate:g}', {'report_rate_hz': rate})
print('children counts:', {k: sum(r['hid_children'] == k for r in rows) for k in (0, 1, 2)},
      ' 2-children in momentum:', sum(r['hid_children'] == 2 and r['hid_momentum'] > 0 for r in rows))
