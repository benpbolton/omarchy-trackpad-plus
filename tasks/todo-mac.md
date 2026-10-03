# Mac task: measure macOS two-finger scrolling

**For:** an agent running on macOS, on the MacBook Pro 14" (M1 Pro, `MacBookPro18,3`) that dual-boots
Omarchy, with a person at the trackpad.
**Branch:** `feat/macos-scrolling-wip` (fork `benpbolton/omarchy-trackpad-plus`).
**Written:** 2026-10-03, on the Omarchy side, which has no Swift toolchain.
**Time:** about 20 minutes, including two short recordings by the person.

## Why this task exists

Trackpad Plus is reproducing macOS trackpad behaviour 1:1 on Omarchy. Pointer movement is done
(draft PR davefano/omarchy-trackpad-plus#16). Scrolling is next. Most of macOS scrolling is open
source, and `scroll_profiles.py` ports it:
- Apple's `IOHIDScrollAccelerator`;
- the momentum decay that WebKit reproduces from the system.

The multitouch driver is closed, though, and only this Mac can tell us its constants:
- raw scroll units per mm of finger travel, and the event rate;
- how the last moments of contact set the first momentum delta;
- the momentum decay, and whether macOS samples a 60 Hz curve or generates frames directly;
- the slowest flick that glides.

`tools/macos/README.md` ("How macOS scrolls a trackpad") explains the model and links every source.
Read it before troubleshooting.

**Output of this task:**
1. `tools/macos/profiles/MacBookPro18-3.json` upgraded to profile version 2, with a measured,
   verified `scroll.driver` (only if the check passes).
2. `tasks/results-mac-scrolling.md`, filled in from the template at the end (always, pass or fail).
3. The raw recordings, pushed to the data branch `data/macos-scrolling` (never to a `feat/` branch).

## Ground rules

- Steps marked **👤** need the person. Tell them exactly what to do, then wait. You cannot scroll.
- Don't change trackpad, display or accessibility settings unless a step says so. Restore anything
  you change, and record it in the results.
- Only read the system. Don't install anything, request permissions, or use the private
  MultitouchSupport framework. It changes how macOS behaves while it runs.
- Never pass `--write` unless the same command printed `PASS` without it.
- **Stop conditions** below mean: write the results file with what you found, push it, and end.
  Don't guess around them.
- Commit code fixes separately from data and results, with a message saying what broke and on which
  macOS/Swift version. Run the test commands in step 1 before every push.
- Don't edit Linux runtime files (`trackpads.py`, `*.qml`, `gestures.py`, …). Don't open, merge or
  rebase pull requests. Don't touch `feat/macos-pointer-profiles`.
- Push only to the fork, `benpbolton/omarchy-trackpad-plus`, never to `davefano`. Remote names
  differ by checkout: on the Mac, `origin` is `davefano` and the fork is `fork`. Commands below
  write the fork's remote name as `FORK`.

## 0. Preconditions

```sh
sysctl -n hw.model                 # expect MacBookPro18,3
sw_vers                            # record in the results
swiftc --version                   # Xcode or Command Line Tools; record it
python3 --version                  # system python3 is fine (stdlib only)
git remote -v | grep 'benpbolton/omarchy-trackpad-plus.*(push)'   # its name is FORK below
ls /tmp/smoke.csv /tmp/scroll*.csv 2>/dev/null   # must print nothing: step 7b uploads every match
```

- **Stop condition:** a different Mac model. The checked profile belongs to `MacBookPro18,3`.
- **Stop condition:** no remote points at `benpbolton/omarchy-trackpad-plus`.
- Move recordings left from an earlier session out of `/tmp` first.
- If `swiftc` is missing, ask the person to run `xcode-select --install`, and wait.
- Use the built-in display, lid open, ideally with no external display attached. The probe fills the
  built-in screen.

## 1. Get the branch and check the code

From the repository root:

```sh
git fetch FORK
git switch feat/macos-scrolling-wip
git pull --ff-only
python3 test_pointer_profiles.py
python3 test_scroll_profiles.py
python3 tools/macos/test_export_profile.py
python3 tools/macos/test_scroll_check.py
```

All four should end with `OK`. `test_trackpads.py` needs Linux, so skip it.

**Stop condition:** a test fails here. Report it, including your Python version.

## 2. 👤 Record the settings, and check that inertia is on

```sh
defaults read -g com.apple.trackpad.scrolling 2>/dev/null || echo "scrolling speed: default"
defaults read -g com.apple.swipescrolldirection 2>/dev/null || echo "natural scrolling: default (on)"
defaults read -g com.apple.trackpad.scaling 2>/dev/null || echo "tracking speed: default"
defaults read com.apple.AppleMultitouchTrackpad TrackpadMomentumScroll 2>/dev/null || echo "momentum key absent"
```

Ask the person to open **System Settings → Accessibility → Pointer Control → Trackpad Options…**
and confirm two things:
- "Use trackpad for scrolling" is on, **with inertia**;
- the Scrolling speed slider position, which you record in the results.

Natural scrolling can be either way; record which. Ask them to set **Displays** to the default
"Looks like" size for the built-in screen. The checked profile was exported at 1512 points wide.

**Stop condition:** they don't want inertia turned on. Momentum is the main thing being measured.

## 3. Add the scroll curves to the checked profile

```sh
python3 tools/macos/export-profile.py --add-scroll tools/macos/profiles/MacBookPro18-3.json
```

Expect `Added N scroll curves at speed S to …; run the scroll check next.` This keeps the
probe-verified pointer half of the profile and adds a `scroll` section whose `driver` is `null`.

If you get one of these messages instead:
- **"publishes no scroll curves"**: see Troubleshooting A.
- **"pointer curves differ" or "built-in display … differ"**: the Mac's display scaling or macOS
  curve set changed since 2026-09-30. Have the person restore the default display scaling and retry.
  If the curves still differ, that's a **stop condition**. Report the difference and don't
  overwrite the profile.

Also capture where macOS keeps the scroll keys and how it set up the accelerator. Both outputs are
for the results and the data branch:

```sh
ioreg -l -w0 | grep -E '"(HIDScroll[A-Za-z]*|ScrollMomentumDispatchRate|HIDTrackpadScrollAcceleration|HIDScrollAccelerationType)"' \
  | sed -E 's/^[ |+-]*//' | sort -u > /tmp/ioreg-scroll.txt
hidutil dump services > /tmp/hidutil-services.txt
grep -n -B3 -A16 'IOHIDScrollAccelerator' /tmp/hidutil-services.txt > /tmp/hidutil-scroll.txt
# hidutil prints XML, with each value on the line after its key: drop identifier keys with their values.
sed -i '' -E '/<key>[^<]*([Ss][Ee][Rr][Ii][Aa][Ll]|[Uu][Uu][Ii][Dd])[^<]*<\/key>/{N;d;}' /tmp/hidutil-scroll.txt
grep -i -E 'serial|uuid' /tmp/ioreg-scroll.txt /tmp/hidutil-scroll.txt   # must print nothing; delete such lines if it does
grep -E '[0-9A-Fa-f]{8}(-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}' /tmp/ioreg-scroll.txt /tmp/hidutil-scroll.txt   # same
```

Read `/tmp/hidutil-scroll.txt`. It should show `IOHIDScrollAccelerator` objects with a `Resolution`
and `Rate` (16.16 values) for the built-in trackpad. Compare them with the profile's
`scroll.resolution` and `scroll.report_rate_hz` (the exporter divides by 65536, and uses 67 when no
rate is published), and write down any mismatch.

## 4. Build the probe and smoke-test it

```sh
swiftc -O tools/macos/scroll-probe.swift -o /tmp/scroll-probe
```

The probe has never been compiled; the Omarchy side has no Swift. If it doesn't compile, fix it in
place, as minimally as possible. Likely spots:
- the `@convention(c)` typealiases;
- `dlsym` with `UnsafeMutableRawPointer(bitPattern: -2)` for `RTLD_DEFAULT`;
- the `Unmanaged` conversions in `hidScroll`;
- `CGEventField(rawValue:)` in the field census;
- the named `CGEventField` scroll cases;
- `class_getInstanceMethod` in `privateValue`.

**Never change the CSV:** `tools/macos/scroll_check.py` parses columns by position. Keep every
row type, column order and header line exactly as written. Commit the fix on its own, for example
`fix(macos): compile scroll-probe with Swift 6.1`.

**👤 Smoke test (10 seconds).** Tell the person: *"A dark full-screen page will open. Scroll it with
two fingers for a few seconds, including one flick, then press Esc."* Then run:

```sh
/tmp/scroll-probe /tmp/smoke.csv --seconds 10
grep '^# hid' /tmp/smoke.csv                                   # want: # hid,1,children,1,attachment,1
awk -F, '$1=="S" && $25!="" && $27!=""' /tmp/smoke.csv | head -3   # raw and accelerated vertical values
grep -c '^S,' /tmp/smoke.csv                                   # scroll events: want hundreds, like V
grep -c '^N,' /tmp/smoke.csv                                   # touch frames: want hundreds
grep -c '^V,' /tmp/smoke.csv                                   # scroll-view offsets: want > 0
```

In S rows, field 25 is `hid_raw_y` and field 27 is `hid_accel_y` (field 1 is the row type `S`).

| What you see | Means | Do |
|---|---|---|
| `# hid,0,…` or empty raw values | private HID symbols weren't found | Troubleshooting B |
| `children,0`, or raw values present but accelerated empty | macOS drops the accelerated child | Fine: the check falls back to AppKit deltas (shape only). Note it. |
| No `N` rows | no touch input | Troubleshooting D |
| No `S` rows | the window isn't receiving scroll events | Troubleshooting D |
| A handful of `S` rows but hundreds of `V` rows | AppKit's responsive scrolling is consuming the gesture | Check that `Paper` still opts out of it |

## 5. 👤 The recording (one to two minutes)

The check needs at least 500 scroll events, 5 long steady strokes and 8 flicks that glide to a
stop, which a minute of deliberate scrolling covers. Two minutes is only the limit; more glides
give the momentum fit and the Linux replay more to work with.

Tell the person, word for word if you like:

> A dark full-screen page will open with instructions and coverage bars. For a minute or two,
> scroll it with two fingers and no clicks, mixing all six kinds of movement, up and down:
> 1. very slow, careful scrolling: stop, then lift
> 2. ordinary scrolling
> 3. flicks, soft and hard, lifted while moving; let most of them glide all the way to a stop
>    without touching
> 4. a few flicks stopped by touching the trackpad mid-glide
> 5. bursts of three or four quick flicks in the same direction
> 6. a few sideways scrolls and flicks
>
> Try to fill every bar. It stops by itself after two minutes. Once you've made at least a dozen
> flicks that glide to a stop, Esc ends it early.

```sh
/tmp/scroll-probe /tmp/scroll.csv
python3 tools/macos/export-profile.py --check-scroll /tmp/scroll.csv --profile tools/macos/profiles/MacBookPro18-3.json
```

Save the full check output for the results. It ends with `PASS` or `FAIL`, followed by these items:

| Item | Requirement | If it fails |
|---|---|---|
| accelerator ≤1 % | the ported IOHIDScrollAccelerator reproduces Apple's value, event by event | Troubleshooting C. **Do not write.** |
| finger mapping within ±10 % | at least 5 long strokes give a consistent units per mm | Record again with longer, steadier strokes |
| ≥8 flicks | enough glides to fit the release | Record again with more flicks |
| momentum within 5 % | the decay model matches the glides | Report the "Direct … %, table … %" line. **Do not write.** |
| every constant measured | nothing missing | See which earlier line is empty |

If only the coverage items fail, record again: `/tmp/scroll-probe /tmp/scroll-2.csv`. Keep every
recording, failed ones too. If it prints `PASS`, store the constants:

```sh
python3 tools/macos/export-profile.py --check-scroll /tmp/scroll.csv --profile tools/macos/profiles/MacBookPro18-3.json --write
python3 tools/macos/export-profile.py --preview tools/macos/profiles/MacBookPro18-3.json --hyprland-scale 2
```

Put the preview output in the results too. It shows the `scroll_points` curve Omarchy would get.

## 6. 👤 Optional: a second scrolling speed

This tests how Apple blends between speed settings, using a separate throwaway profile.
1. Ask the person to move **Scrolling speed** two notches away from where it was (step 2), and note
   the new position.
2. Run:
   ```sh
   python3 tools/macos/export-profile.py --output /tmp/speed2.json
   /tmp/scroll-probe /tmp/scroll-speed2.csv      # 👤 same two-minute routine
   python3 tools/macos/export-profile.py --check-scroll /tmp/scroll-speed2.csv --profile /tmp/speed2.json
   ```
3. Ask the person to put Scrolling speed back. Confirm the value matches step 2:
   `defaults read -g com.apple.trackpad.scrolling`.

Only the accelerator line matters here. The other constants should roughly agree with step 5.
Don't copy anything from `/tmp/speed2.json` into the repository.

## 7. Return everything

### 7a. Results and profile on the feature branch

1. Fill in `tasks/results-mac-scrolling.md` from the template below.
2. Validate the profile:
   ```sh
   python3 -c "import json,sys; sys.path.insert(0,'.'); import pointer_profiles as p; v=p.load_profile(open('tools/macos/profiles/MacBookPro18-3.json','rb').read()); print(v['version'], v['scroll']['driver'] is not None)"
   ```
3. Run the step-1 tests, then commit and push:
   ```sh
   git add -f tasks/results-mac-scrolling.md tools/macos/profiles/MacBookPro18-3.json   # the Mac excludes tasks/
   git commit -m "data(macos): measure two-finger scrolling on MacBookPro18,3"
   git push FORK feat/macos-scrolling-wip
   ```
   If the check failed, commit the results file only. The profile must stay without a measured
   driver: either restore it with `git checkout tools/macos/profiles/MacBookPro18-3.json`, or keep
   the version-2 export whose `driver` is `null`, and say which in the results.

### 7b. Recordings on the data branch

The CSVs hold only motion data and screen size. They're too big for a feature branch, so they go
on an orphan branch that is never merged:

```sh
repo="$(git rev-parse --show-toplevel)"
fork="$(git -C "$repo" remote -v | awk '/benpbolton\/omarchy-trackpad-plus/ && /\(push\)/ { print $1; exit }')"
url="$(git -C "$repo" remote get-url "${fork:?no remote points at benpbolton/omarchy-trackpad-plus}")"
data="$(mktemp -d)/data"
if git ls-remote --exit-code --heads "$url" data/macos-scrolling >/dev/null 2>&1; then
  git clone -q --branch data/macos-scrolling "$url" "$data"
else
  git clone -q --no-checkout "$repo" "$data" && git -C "$data" remote set-url origin "$url" \
    && git -C "$data" switch -q --orphan data/macos-scrolling
fi
day="$data/$(date +%F)"; mkdir -p "$day"
for f in /tmp/scroll*.csv /tmp/smoke.csv; do [ -f "$f" ] && gzip -c "$f" > "$day/$(basename "$f").gz"; done
cp /tmp/ioreg-scroll.txt /tmp/hidutil-scroll.txt "$day/"
[ -f /tmp/speed2.json ] && cp /tmp/speed2.json "$day/"
cp "$repo/tools/macos/profiles/MacBookPro18-3.json" "$day/profile-after-check.json"
du -sh "$day"/*                                     # each file well under 50 MB
git -C "$data" add -A && git -C "$data" commit -q -m "data: macOS scroll recordings $(date +%F)"
git -C "$data" push -u origin data/macos-scrolling
git -C "$data" rev-parse HEAD                       # put this hash in the results
```

Then add that hash to the results file, commit, and push the feature branch again.

## Troubleshooting

**A. "publishes no scroll curves".** Find where the keys live:
`ioreg -l -w0 | grep -n -E 'HIDScrollAccelCurves|HIDScrollResolution' | head`, then look upward in
`ioreg -l -w0` for the owning class (the `+-o Name  <class …>` line above it). Add that class to the
`sources` list in `scroll_section()` in `tools/macos/export-profile.py`, and add a case to
`ScrollExportTests` in `tools/macos/test_export_profile.py`. Run the tests, commit, then retry step 3.

**B. HID values missing.** Check which symbols resolve:

```sh
python3 - <<'EOF'
import ctypes
libs = ['/System/Library/Frameworks/IOKit.framework/IOKit',
        '/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics',
        '/System/Library/PrivateFrameworks/SkyLight.framework/SkyLight']
names = ['CGEventCopyIOHIDEvent', 'IOHIDEventGetFloatValue', 'IOHIDEventGetTimeStamp', 'IOHIDEventGetChildren',
         'IOHIDEventGetEventFlags', 'IOHIDEventGetType', 'IOHIDEventGetPhase', 'IOHIDEventGetScrollMomentum',
         '_IOHIDEventCopyAttachment']
for lib in libs:
    handle = ctypes.CDLL(lib)
    print(lib.rsplit('/', 1)[1], [n for n in names if hasattr(handle, n)])
EOF
```

If a symbol exists only in one framework, `dlopen` that framework in `symbol()` before `dlsym`. Keep
the CSV unchanged.

If `CGEventCopyIOHIDEvent` is missing altogether, it's a **stop condition**. Push the smoke test,
plus a recording made anyway: the `F` rows (every non-zero CGEvent field) may show where raw deltas
live.

**C. Accelerator error above 1 %.** Don't write. You may test hypotheses offline against the same
CSV in a scratch script, without changing the repository:
- `resolution` and `report_rate_hz` read as plain numbers instead of 16.16;
- the X resolution instead of Y;
- momentum without the `dispatch_rate` scaling;
- dropping rows where `hid_children` is 0;
- events missing from the history because the person scrolled outside the window.

Start from:

```sh
python3 - <<'EOF'
import json, sys
sys.path[:0] = ['.', 'tools/macos']
import pointer_profiles as pp, scroll_check as c
profile = pp.load_profile(open('tools/macos/profiles/MacBookPro18-3.json', 'rb').read())
recording = c.read_recording('/tmp/scroll.csv')
for name, change in [('as exported', {}), ('rate plain', {'report_rate_hz': 67.0})]:
    trial = json.loads(json.dumps(profile)); trial['scroll'].update(change)
    errors, reference, _ = c.check_accelerator(trial, recording['scroll'])
    print(name, reference, 'median %', errors[len(errors) // 2] if errors else None, 'n', len(errors))
EOF
```

Report each hypothesis with its median error. If one fixes it, describe the change; the Linux side
will update `scroll_profiles.py` and its tests. Only commit a model change yourself if it comes with
a test that pins the new behaviour and every step-1 test still passes.

**D. Probe gets no events.**
- **No `S` rows:** the window must be frontmost. Click its dock icon, or make sure no other
  full-screen app covers it.
- **No `N` rows:** touches don't reach the page view, so units per mm can't be measured. Check that
  the person is touching the built-in trackpad. If touches still don't arrive, it's a **stop
  condition**; report what you tried.

## Results template: `tasks/results-mac-scrolling.md`

```markdown
# Results: macOS scrolling measurement

- Date / agent:
- macOS (sw_vers) / model / swiftc version:
- Settings during recording: scrolling speed (slider + defaults value), natural scrolling,
  inertia on?, tracking speed, display "Looks like":
- Changed and restored settings:

## Export
- `--add-scroll` output:
- scroll section: speed, resolution, report_rate_hz, momentum_rate_hz, natural, number of curves:
- Where the keys live (ioreg classes) and anything surprising:
- hidutil IOHIDScrollAccelerator Resolution / Rate (16.16 and decimal), matches the profile?:

## Probe
- Compile: clean / fixed (commit hash, what changed):
- Smoke test header line and checks:
- Recordings (file, scroll events, touch frames, coverage notes):

## Check
- Full `--check-scroll` output for each recording (paste verbatim):
- PASS/FAIL; written to the profile? (commit hash):
- `--preview` scrolling section (paste):
- Second speed (if done): settings, accelerator line:
- Troubleshooting C hypotheses tried, with median errors:

## Observations for the Linux side
- Momentum dispatch rate seen; table vs direct; interruption latency; AppKit boost by scroll
  count; scroll-view ratio; anything unexpected in the F (field census) rows:

## Data
- Branch `data/macos-scrolling` commit:
- Files:

## Open questions
```

## Handoff back to Omarchy

On the Linux side:

```sh
git fetch FORK && git switch feat/macos-scrolling-wip && git pull --ff-only
git fetch FORK data/macos-scrolling
```

Then read `tasks/results-mac-scrolling.md`. What comes next, there:
1. the libinput `scroll_points` layer and its UI: Natural scrolling, off by default, plus Scrolling speed;
2. the Hyprland plugin for exact acceleration and momentum, verified by replaying these recordings.
