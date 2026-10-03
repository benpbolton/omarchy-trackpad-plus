# macOS scroll recordings, 2026-10-03

MacBookPro18,3, macOS 15.7.9 (24G830). Scrolling speed is the default (0.3125), natural scrolling
is off, and inertia is on. Results: `tasks/results-mac-scrolling.md` on `feat/macos-scrolling-wip`.

- `scroll-3.csv.gz`: the main recording (13 glides that ran out, touches present).
- `scroll-2.csv.gz`: touches present, every glide cut short by the next stroke.
- `scroll.csv.gz`: no touch frames, every glide stopped.
- `smoke.csv.gz`: a 10-second smoke test.
- `smoke-responsive.csv.gz`: the smoke test before the responsive-scrolling fix (4 events).
- `check-*.txt`: `--check-scroll` output for each recording.
- `ioreg-scroll.txt`, `hidutil-scroll.txt`: where the scroll keys live, and the live
  `IOHIDScrollAccelerator`. Identifier keys and values are removed.
- `profile-after-check.json`: the version-2 profile from `--add-scroll` (`driver: null`).
- `analysis/`: the Troubleshooting C scripts. Run them from the repository root with a
  decompressed CSV, for example `python3 hyp.py scroll-3.csv`.
