from pathlib import Path
import json, math, statistics as st, sys, collections
sys.path[:0] = ['.', 'tools/macos']
import pointer_profiles as pp, scroll_profiles as sp, scroll_check as c
profile = pp.load_profile(open(Path(__file__).resolve().parent.parent / 'profile-after-check.json', 'rb').read())
rows = c.read_recording(sys.argv[1])['scroll']

class Probe(sp.ScrollAccelerator):
    """Same as the port; also remembers how many events it averaged and over what interval."""
    def accelerate(self, scroll, seconds, dispatch_rate=None):
        before_tail = self.tail
        out = super().accelerate(scroll, seconds, dispatch_rate)
        n = (self.head - self.tail) % sp.AVERAGE_LENGTH or sp.AVERAGE_LENGTH
        self.info = n
        return out

f = sp.scroll_function(profile); s = profile['scroll']
axes = {n: Probe(f, s['resolution'], s['report_rate_hz']) for n in 'xy'}
by_count, by_phase, first = collections.defaultdict(list), collections.defaultdict(list), []
prev_t = {}
for r in rows:
    if not math.isfinite(r['hid_time']): continue
    mom = r['hid_momentum'] > 0
    for n, a in axes.items():
        raw, act = r[f'hid_raw_{n}'], r[f'hid_accel_{n}']
        if not math.isfinite(raw) or not raw: continue
        gap = (r['hid_time'] - prev_t.get(n, -9)) * 1000; prev_t[n] = r['hid_time']
        p = a.accelerate(raw, r['hid_time'], 120.0 if mom else None)
        if mom or not (math.isfinite(act) and abs(act) > 1e-6): continue
        ratio = p / act
        by_count[a.info].append(ratio); by_phase[int(r['phase'])].append(ratio)
        if gap > 500: first.append(ratio)
q = lambda v: f"n={len(v):4d} ratio median {st.median(v):.4f}  p25 {st.quantiles(v, n=4)[0]:.4f}  p75 {st.quantiles(v, n=4)[2]:.4f}" if len(v) > 3 else f"n={len(v)} {v}"
print('first delta after a >500 ms pause:', q(first))
for k in sorted(by_count): print(f'history span {k}:', q(by_count[k]))
for k in sorted(by_phase): print(f'phase {k}:', q(by_phase[k]))
