# Results: macOS scrolling measurement

**Outcome: FAIL, not written.** The accelerator check fails, so the profile has no measured
driver. All other items pass on the main recording (`scroll-3.csv`). Momentum is solved: Apple's
scaling at the measured 120 Hz rate reproduces every momentum value exactly. Contact scrolling is
still about 18 % off. The cause is the history the accelerator keeps during a stroke, and nothing
the app can see so far reconstructs it.

- Date / agent: 2026-10-03, Claude Code (Claude Opus 5.5) on the Mac, with Ben at the trackpad.
- macOS (sw_vers) / model / swiftc version: macOS 15.7.9 (24G830) / `MacBookPro18,3` / Apple Swift
  6.0.3 (swiftlang-6.0.3.1.10). Step-1 tests pass on Python 3.14.6 (Homebrew) and 3.9.6 (system).
- Settings during recording:
  - Scrolling speed: default. The `defaults` key is absent; the accelerator's AccelIndex is 0.3125.
    The slider position wasn't read separately.
  - Natural scrolling: **off** (`com.apple.swipescrolldirection` = 0).
  - Inertia: on. The person confirmed it in Accessibility, and `TrackpadMomentumScroll` = 1.
  - Tracking speed: 0.875.
  - Display: built-in only, default "Looks like" (probe header: 1512 × 982 points, backing scale 2).
- Changed and restored settings: none.

## Export
- `--add-scroll` output: `Added 10 scroll curves at speed 0.3125 to tools/macos/profiles/MacBookPro18-3.json; run the scroll check next.`
- scroll section:
  - speed 0.3125, resolution 400.0, natural false, 10 curves;
  - report_rate_hz 67.0, the fallback: no `HIDScrollReportRate` is published;
  - momentum_rate_hz 60.0, the default. `ScrollMomentumDispatchRate` isn't in ioreg, and it doesn't
    reach apps either; see Observations.
- Where the keys live: `HIDScrollAccelCurves`, `HIDScrollResolution[X|Y|Z]` and
  `HIDScrollAccelerationType` (`HIDTrackpadScrollAcceleration`) are on both
  `AppleMultitouchDevice` and `AppleMultitouchTrackpadHIDEventDriver`, inside
  `DefaultMultitouchProperties`. All three resolutions are 26214400 (400.0). There is also a legacy
  `HIDScrollAccelerationTable`, and `HIDPointerReportRate` = 120.
- hidutil IOHIDScrollAccelerator, for each of X, Y and Z:
  - Resolution 26214400 = 400.0 and Rate 4390912 = 67.0, matching the profile;
  - algorithm `IOHIDParametricAcceleration` with AccelIndex 20480 = 0.3125, matching the profile's
    speed.

## Probe
- Compile: clean on the first try (one Swift 6 concurrency warning on `app.terminate`, harmless in
  Swift 5 mode). Running it found three problems, each fixed in its own commit:
  - `72e6d7d`: AppKit's responsive scrolling handled a gesture's changed and momentum events off
    `-sendEvent:`, so the local monitor saw 4 events while the view moved 760 times. `Paper` now
    opts out. That only changes AppKit's scroll-view path (the V rows), not the HID events.
  - `082debc`: one recording got no touch frames. Touches go to the view under the pointer, so the
    probe now has no scrollers, and its overlay asks for a click if touches don't arrive.
  - `d072312`: the flicks bar counted glides that began, and every glide was being cut short by the
    next stroke. A "full glides" bar now counts only glides that end without the interrupted flag.
- Smoke test header line and checks: `# hid,1,children,1,attachment,1`. After `72e6d7d`: 1098 S,
  674 N, 747 V, and 498 momentum rows with accelerated values.
- Recordings:

| File | Length | Scroll events | Touch frames | Glides (ran out) | Notes |
|---|---|---|---|---|---|
| `smoke-responsive.csv` | 4.2 s | 4 | 903 | — | before `72e6d7d`; too few events for the check |
| `smoke.csv` | 9.5 s | 1098 | 674 | 13 (0) | |
| `scroll.csv` | 42.8 s | 5140 | 0 | 53 (0) | touches lost; the empty "stopped" bar led to stopping every glide |
| `scroll-2.csv` | 33.5 s | 3677 | 2295 | 44 (0) | each glide cut 0.2–0.4 s in by the next stroke |
| `scroll-3.csv` | 52.6 s | 4799 | 2427 | 38 (13) | **main recording**, after `d072312` |

## Check
- Full `--check-scroll` output for each recording:

`smoke.csv`
```
Scroll events: 16 strokes; contact events at 213.5 Hz.
Apple's scroll accelerator, event by event against HID accelerated values: median error 20.16 % over 1316 values (3% within 0.5 %).
Points per accelerated unit: AppKit 12.029, CGEvent 11.465; scroll view moved 1.088 points per AppKit point.
AppKit points per unit by scroll count: 1: 10.134, 2: 10.095, 3: 11.406, 4: 10.442, 5: 10.646, 6: 11.447, 26: 12.785
Raw units per finger mm: 16.358 from 11 strokes (interquartile spread 4.6 %).
Release: mean of the last 50 ms × 0.965 (13 flicks, log spread 0.104); momentum starts above 1063 units/s.
A landing finger stops momentum after 1 ms (median of 8).

FAIL: accelerator ≤1 % ✗; finger mapping within ±10 % ✓; ≥8 flicks ✓; momentum within 5 % ✗; every constant measured ✗
```

`scroll.csv`
```
Scroll events: 57 strokes; contact events at 215.0 Hz.
Apple's scroll accelerator, event by event against HID accelerated values: median error 24.35 % over 6260 values (2% within 0.5 %).
Points per accelerated unit: AppKit 12.227, CGEvent 11.822; scroll view moved 0.751 points per AppKit point.
AppKit points per unit by scroll count: 1: 10.138, 2: 10.191, 3: 12.095, 4: 10.794, 5: 10.903, 6: 11.426, 7: 10.933, 8: 11.135, 16: 11.795, 17: 23.591
Raw units per finger mm: nan from 0 strokes (interquartile spread nan %).
Release: mean of the last 50 ms × 0.911 (53 flicks, log spread 0.124); momentum starts above 329 units/s.

FAIL: accelerator ≤1 % ✗; finger mapping within ±10 % ✗; ≥8 flicks ✓; momentum within 5 % ✗; every constant measured ✗
```

`scroll-2.csv`
```
Scroll events: 50 strokes; contact events at 213.2 Hz.
Apple's scroll accelerator, event by event against HID accelerated values: median error 22.60 % over 4316 values (2% within 0.5 %).
Points per accelerated unit: AppKit 11.810, CGEvent 11.435; scroll view moved 0.857 points per AppKit point.
AppKit points per unit by scroll count: 1: 10.126, 2: 10.144, 3: 12.428, 4: 11.005, 5: 11.281, 6: 10.900, 7: 12.547, 8: 11.013, 9: 12.492, 10: 11.250, 11: 12.078, 13: 11.658, 14: 11.663, 15: 11.664, 16: 12.193, 17: 11.890, 18: 11.983, 36: 13.756
Raw units per finger mm: 16.124 from 42 strokes (interquartile spread 4.3 %).
Release: mean of the last 50 ms × 0.918 (44 flicks, log spread 0.095); momentum starts above 671 units/s.
A landing finger stops momentum after 2 ms (median of 15).

FAIL: accelerator ≤1 % ✗; finger mapping within ±10 % ✓; ≥8 flicks ✓; momentum within 5 % ✗; every constant measured ✗
```

`scroll-3.csv`
```
Scroll events: 45 strokes; contact events at 210.2 Hz.
Apple's scroll accelerator, event by event against HID accelerated values: median error 25.33 % over 5419 values (2% within 0.5 %).
Points per accelerated unit: AppKit 12.130, CGEvent 11.999; scroll view moved 1.047 points per AppKit point.
AppKit points per unit by scroll count: 1: 10.137, 2: 10.120, 3: 11.682, 13: 11.504
Raw units per finger mm: 15.958 from 35 strokes (interquartile spread 4.2 %).
Release: mean of the last 50 ms × 0.915 (38 flicks, log spread 0.141); momentum starts above 421 units/s (overlaps stopped strokes).
Momentum at 119.9 Hz, direct frames: median distance error 0.7 % over 13 glides (duration ×1.25); decay 0.975→0.91. Direct 0.7 %, table 2.0 %.
A landing finger stops momentum after 1 ms (median of 14).

FAIL: accelerator ≤1 % ✗; finger mapping within ±10 % ✓; ≥8 flicks ✓; momentum within 5 % ✓; every constant measured ✓
```

- PASS/FAIL: FAIL on every recording; nothing written.
  - The profile was **restored** with `git checkout` to the version-1 pointer profile.
  - Keeping the version-2 export (`driver: null`) broke two tests in `test_export_profile.py`:
    `test_add_scroll_keeps_the_checked_pointer_half` and
    `test_pointer_only_profiles_cannot_be_scroll_checked`. Both assume the checked-in profile has no
    scroll section, so a passing `--write` would break them too.
  - The version-2 export is on the data branch as `profile-after-check.json`.
- `--preview` scrolling section: `Scrolling: run the scroll check (scroll-probe.swift) to measure the driver first.`
  It needs a measured driver.
- Second speed: skipped. It only tests the accelerator line, which fails at the current speed.
- Troubleshooting C hypotheses, on `scroll-3.csv` (5419 values; median error, overall / contact /
  momentum):

| Hypothesis | Overall | Contact | Momentum |
|---|---|---|---|
| as exported | 25.33 % | 18.43 % | 30.10 % |
| resolution and report rate read as plain numbers | 100 % / 38818 % | | |
| X resolution instead of Y | no change: X, Y and Z are all 400 | | |
| **momentum scaled to 60 Hz from the measured 120 Hz (attachment missing)** | **1.25 %** | 18.65 % | **0.00 %** |
| drop rows with `hid_children` 0 | none exist: every accelerated row has 2 children, and the 104 rows with 1 child carry no accelerated copy | | |
| events missed outside the window | not possible: full-screen window on the only display | | |
| report rate 100 / 120 / 125 / 210 Hz | 57 % / 138 % / 160 % / 564 % | | |
| contact split into two histories (alternating, or by a 2–4.5 ms gap) | 1.35–1.54 % | 16.98–22.80 % | 0.00 % |
| short-gap events left out of the history | 1.43–1.60 % | 21.13–22.61 % | 0.00 % |

## Observations for the Linux side
- **Momentum dispatch rate:** 119.9 Hz from the event timestamps (ProMotion). Frames are generated
  directly at that rate, not sampled from a 60 Hz table (direct 0.7 %, table 2.0 %).
  - Apple's `IOHIDPointerScrollFilter` reads `ScrollMomentumDispatchRate` with the same
    `_IOHIDEventCopyAttachment` call the probe uses. The probe gets nothing, so the attachment
    exists in the HID event system but is stripped before the event reaches an app.
  - Scaling momentum by 120/60 makes the port exact (0.00 % median). Proposed: when the attachment
    is missing, the check (and the profile's `momentum_rate_hz`) should use the measured momentum
    cadence.
- **Contact accelerator:**
  - Began events match Apple: 51 of them, median ratio 1.0002, interquartile 1.0000–1.0002. So the
    curve, resolution, rate and 0.1 wheel scale are right. A few starts differ, for example by
    exactly 2×.
  - The error grows with history: the port runs about 19 % high once its 9-event window fills.
  - Contact events average 210 Hz and come in pairs: a large delta on an ~8 ms beat, then a small
    one 1–2 ms later. The flags are identical (0x2000010), and every accelerated row has 2 children.
  - The `accelerate` port matches IOHIDFamily-2115.140.4 line by line. My working hypothesis is
    that Apple's history holds events, or timestamps, that apps never see.
  - The next step needs more than the CSV holds: each child's type and the HID sender ID. That's a
    CSV format change, so it's the Linux side's call.
- **The gate mixes contact and momentum in one median.** With momentum fixed it reads 1.25 % while
  contact is still 18.65 % off. A momentum-heavy recording could pass on a broken contact model.
  Proposed: gate contact and momentum separately.
- **Interrupted flag:** End|Interrupted (`20`) marks every glide stopped by a landing finger,
  including one cut short by the next stroke. `INTERRUPTED = 1 << 4` is right; WebKit's
  `IOKitSPIMac.h` defines `kIOHIDEventScrollMomentumInterrupted = (1 << 4)`. A landing finger stops
  momentum after 1–2 ms (medians of 8–15).
- **Finger mapping:** 15.96 raw units per mm (35 strokes, 4.2 % spread). The other recordings gave
  16.12 and 16.36.
- **Release:** mean of the last 50 ms × 0.915 (38 flicks). The other recordings gave 0.911–0.965.
  The momentum threshold varies (329–1063 units/s) and overlaps stopped strokes.
- **AppKit and the scroll view:**
  - AppKit points per accelerated unit: 11.8–12.2; CGEvent: 11.4–12.0.
  - Boost by scroll count: about 10.1 at counts 1–2, and 10.8–12.5 above. Outliers: 13.8 at 36,
    and 23.6 at 17.
  - Scroll-view ratio: 0.75–1.09 points per AppKit point. This is with responsive scrolling off.
- **F census (`scroll-3.csv`):**
  - The events carry **public** fields 175–178, which the macOS 15 SDK names
    `kCGScrollWheelEventAcceleratedDeltaAxis2/1` and `kCGScrollWheelEventRawDeltaAxis2/1`. They're
    worth comparing with the HID values: they could replace the private `CGEventCopyIOHIDEvent`
    path.
  - Fields with no public name: 50–53, 55, 58, 85, 87, 101, 106, 107, 119, 125, 126, 139, 142
    and 169.
  - Field 40 is the target PID. No identifiers.

## Ideas for the probe (documented only, not implemented)
- **A scrolling course instead of a coverage checklist (Ben's idea).** The page scrolls under a
  fixed crosshair along a drawn path, and the person steers to keep the crosshair on it.
  - Each section of the path draws out one movement the check needs:
    - long straights for steady strokes;
    - tight turns for slow, careful scrolling;
    - far targets that a flick must reach and glide into, untouched;
    - "catch" gates where a glide has to be stopped;
    - sideways stretches.
  - It makes the two minutes more entertaining. Coverage comes from the course design rather than
    instructions, which this session showed get misread: no glide ran out in the first three
    recordings.
  - Caveats: the page must still be the same kind of NSScrollView, so the events are what an app
    sees. Steering toward targets may bias speeds, since people slow down near them, so the check
    should keep classifying strokes from the recording itself.

## Data
- Branch `data/macos-scrolling` commit: `c8c6e494dfcdf964fa42ad01b10219d809ba37d9` (fork `benpbolton/omarchy-trackpad-plus`)
- Files: `2026-10-03/`: five gzipped recordings (`smoke-responsive`, `smoke`, `scroll`, `scroll-2`, `scroll-3`), `check-*.txt`, `ioreg-scroll.txt`, `hidutil-scroll.txt`, `profile-after-check.json`, `analysis/` (the hypothesis scripts) and a README.

## Open questions
- What else feeds `IOHIDScrollAccelerator`'s history during contact? The candidates are events
  apps never receive, or timestamps that differ from `IOHIDEventGetTimeStamp` on the delivered copy.
- Should the probe record each child's type and the HID sender ID (CSV version 2) to find out?
- Should `momentum_rate_hz` in the profile hold the measured 120 Hz, since the attachment never
  reaches apps?
- The export tests use the checked-in profile as their pointer-only fixture. They should build that
  fixture by dropping `scroll`, so step 7a's "keep the version-2 export" and a future `--write` can
  both land.
