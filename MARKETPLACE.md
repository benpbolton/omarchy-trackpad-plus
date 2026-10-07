# Marketplace submission

Trackpad Plus is being prepared for the
[Omarchy Plugin Marketplace](https://omarchyplugins.com/). Submission is a
[GitHub issue](https://github.com/omacom/omarchy-plugin-marketplace/issues/new?template=submit-plugin.yml),
followed by compatibility validation, a static security baseline, and explicit
maintainer approval of the exact commit. A preparation PR does not publish a
listing. Follow the current [submission guide](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SUBMISSION.md)
and [security policy](https://github.com/omacom/omarchy-plugin-marketplace/blob/main/SECURITY.md).

## Listing metadata

| Field | Value |
| --- | --- |
| Repository | https://github.com/davefano/omarchy-trackpad-plus |
| Name | Trackpad Plus |
| Permanent plugin ID | `davefano.trackpad-plus` |
| Category | `Hardware` |
| Tags | `bar`, `hyprland`, `quickshell` |
| License | MIT, retaining Andrew Kent and David Fano notices |
| Preview | Root `preview.png`, 430 × 630 pixels |

The repository is public and contains one root manifest, an existing entry
point, README installation/removal/dependency instructions, and a root license.
No matching ID or repository was found in the marketplace registry during the
September 15 check. Recheck uniqueness, including retired IDs, before submitting;
marketplace IDs are permanent. The original `awkent01.touchpad` is a separate
listing. No ID rename is needed for this derivative.

## Current candidate — October 6, 2026

The candidate now includes release `2026.10.05.0`: model-specific Apple Magic
Trackpad palm controls and the explicitly installed typing guard. The portable
runner includes `test_palm.py` and `test_typing_guard.py`; host checks also include
`tst_palm.qml`. These supplement the existing backend, gesture, overview,
installation, selection, syntax, and manifest checks. The complete host command
passed on the Dell XPS (x86_64) during this October 6 refresh, including all four
Qt suites and both isolated Quickshell IPC checks. This verifies automated host
integration, not physical swipe acceptance or live GPU capture.

The September results below remain historical evidence for their exact SHA.
Before marketplace submission, rerun the marketplace baseline against the final
merged SHA and complete the remaining hardware acceptance checks. This PR does
not submit a listing or imply that newer runtime changes have marketplace
approval. The typing guard was physically verified on the Dell XPS with an
external Apple Magic Trackpad during the October 5 release work; Mac hardware
acceptance remains separate.

## Release evidence — September 15, 2026

These results cover runtime source at
[`d6d35e1`](https://github.com/davefano/omarchy-trackpad-plus/commit/d6d35e13026ff4af4a4b88722eadee2697870a85),
version `2026.09.15.2`. The preparation PR adds test orchestration and
documentation without changing plugin runtime behavior. Approval still needs
the final merged commit SHA; these results do not cover later runtime changes
or unmerged PR #12.

Host: MacBook Air M2, aarch64, Omarchy 4.0.3, Hyprland 0.56.2,
libinput 1.31.3, Quickshell 0.3.1, Qt 6.11.2.

| Check | Result |
| --- | --- |
| `bash tools/check.sh host` | Passed: all checks below |
| Python backend / gestures / controller / lock observer / installation / overview IPC | 48 / 49 / 23 / 13 / 19 / 2 tests passed (154 total) |
| Node selection and overview model suites | Passed |
| Offscreen inherited panel IPC | All five commands passed |
| Qt curve / gesture / overview suites | 12 / 13 / 18 entries passed, including setup/cleanup; none skipped |
| QML lint | 12 sources passed with 95 specifically allowed host metadata diagnostics |
| `omarchy plugin validate .` | Passed |
| Legacy Perl/Bash syntax and Git whitespace | Passed |
| Live overview, `python3 tools/overview-check/check.py --cycles 10` | Passed on M2: actual current/inactive/fullscreen fixture pixels, selection, focus, wallpaper, workspace creation, forced exit and observer cleanup |
| Installed-copy upgrade, profile Apply/Restore, shell restart/reload, gesture restore, removal and rollback | Passed: version 2026.09.15.0 upgraded temporarily to candidate .2; pointer settings/undo, generated Lua, input, layout, enabled state and original plugin restored afterward |

The live run measured 347 ms cold open and 192 ms median warm open. RSS was
196,464 KiB before, 251,408 KiB peak, and 194,672 KiB after; file descriptors
were 49, 74, and 49. Ten cycles are a smoke test, not a memory or performance
guarantee. The harness uses temporary instrumented copies of the production
overview, owned terminal fixtures, and temporary workspaces; it restores focus
and writes no preview images. It does not exercise physical swipe recognition.

The session already had a failed system `omarchy-wifi-resume-fix.service`
before the remaining installation checks. No failed user services were present.
Do not attribute that existing Wi-Fi failure to this plugin.

The installed-copy check used a complete plugin/configuration backup and bounded
waits for the shell to register panel IPC after file replacement. It applied a
temporary pointer profile, verified persistence through shell restart and
Hyprland reload, restored the exact original settings and generated Lua, used
Restore original for the managed gesture block, and ran `omarchy plugin remove`.
Removal retained pointer state and rules as documented. The original plugin,
layout, input, settings, previous-profile history, enabled state, and idle
overview companion were restored. Fresh state initialization is covered by the
temporary-installation tests, not by this existing-user desktop upgrade.

### Marketplace preflight

The marketplace's `inspectSubmission`, duplicate/retired-ID check, and
`runSecurityBaseline` were run against public commit `d6d35e1`, using marketplace
tooling at `b2b1788a0bcee61cd55baefb53926ee5f7454aac`.
Compatibility, root preview detection, and ID availability passed. Baseline v3
returned **review-required**, with **zero findings** and one `installer`
capability because the filename `test_install.py` matches its setup-file rule.
That file is an automated test using temporary state and a fake compositor,
not a plugin installation hook. Explain this exact capability to the reviewer;
do not rename or hide it to bypass review. This preflight is not marketplace
approval and must be repeated for the final submitted SHA.

## Before submission

- [x] Review [PR #12](https://github.com/davefano/omarchy-trackpad-plus/pull/12)
  and exclude it from this preparation PR. Its pointer-resolution changes require
  fixes for duplicate device identity and retaining calibration when a device
  disconnects. An exact-head review at `6988ea5` reproduced both issues despite
  all 51 trackpad tests passing: same-name 47/80 units/mm devices both use the
  first match, and a disconnected Magic Trackpad rewrites spacing from 0.11938
  to 0.1. Existing custom/undo curves also change feel on upgrade without a
  schema migration; settle that compatibility decision before inclusion. Its
  author's x86_64 test report is separate evidence for that PR, not rendering
  validation of this release. The current high-resolution sensor limitation is
  documented in the README. Do not merge the proposed fix solely to prepare
  the listing; review and retest it as a separate runtime change.
- [ ] Merge the preparation PR after its hosted portable checks pass, then
  record the full final `main` SHA and rerun relevant checks if runtime changes.
- [x] Complete the scripted live upgrade/removal, profile Apply/Restore,
  shell-restart, reload, and rollback checks with recoverable backups.
- [ ] Run the interactive production lock check with someone present to unlock:
  `python3 tools/overview-check/check_lock.py`. Record capture teardown,
  observer restart, rejected opens while locked, and remaining closed on unlock.
- [ ] Record hands-on pointer and gesture acceptance on the submitted version.
  Keep x86_64 overview rendering and untested hardware explicitly unverified;
  keep the overview experimental until those checks pass.
- [x] Run marketplace compatibility and baseline preflight against current main;
  record the setup-test capability requiring maintainer review above.
- [ ] Repeat the marketplace checks against the final merged submission SHA.
- [ ] Confirm rights to the plugin and preview assets, review every submission
  statement, and obtain the owner's approval of the completed issue title/body.

CI runs the portable suite on GitHub-hosted Ubuntu with no repository secrets
and a read-only token. Qt/Quickshell host tests and live hardware checks remain
separate. CI configuration is a project release practice, not an additional
marketplace submission requirement.

## Submission draft

Title: **[Plugin]: Trackpad Plus**

The unchecked items below intentionally prevent this draft from being treated
as a completed submission. Check each only after verifying it with the owner.
Keep all six headings, their order, and the checklist wording when copying to
the issue. Add the final commit and test evidence to Maintainer notes.

```markdown
### Repository URL

https://github.com/davefano/omarchy-trackpad-plus

### Category

Hardware

### Tags

bar, hyprland, quickshell

### Suggest a missing tag

_No response_

### Maintainer notes

Independently maintained MIT-licensed derivative of Andrew Kent's
omarchy-touchpad-widget; original history and copyright are preserved.
Provides per-device pointer/scroll controls and explicit gesture management.
Requires Omarchy's Quickshell shell and Lua-based Hyprland configuration,
Python 3, libinput custom acceleration, hyprctl, and GNU timeout.
The bundled Quickshell overview is experimental; rendering has been tested
on an M2/aarch64 host, not x86_64. HyMission is a separately installed optional
provider and is unavailable on ARM64.
Custom/Mac-inspired profiles can feel too fast on high-resolution sensors;
the proposed per-sensor correction is not part of this submission candidate.
No privileged plugin installation or runtime package installation is needed.
The baseline flags test_install.py as an installer by filename; it is a test
using temporary state and a fake compositor, not an installation hook.
Gesture edits require Apply gestures and support Restore original. Device
settings persist after plugin removal; README documents cleanup and recovery.
See MARKETPLACE.md for release evidence and remaining compatibility limits.

### Submission checklist

- [ ] The repository is public and contains installation and removal instructions.
- [ ] I have documented the plugin license and any external dependencies.
- [ ] I confirm that I own or have permission to submit this plugin and its preview assets.
- [ ] The plugin does not overwrite user configuration without explicit consent.
- [ ] I understand that approval is for listing and is not a security review.
```

After approval, save the completed body to a temporary file and submit:

```sh
gh issue create --repo omacom/omarchy-plugin-marketplace \
  --title '[Plugin]: Trackpad Plus' --body-file /path/to/completed-submission.md
```

Fix validation feedback on the existing issue rather than creating duplicates.
A marketplace maintainer applies `approved-and-verified` after reviewing the
current reports. Later upstream commits need their own verification; an old
approval does not cover a newer release.
