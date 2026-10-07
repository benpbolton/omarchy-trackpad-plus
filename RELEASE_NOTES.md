# 2026.10.05.0 — Apple palm rejection and typing protection

This release adds native palm-rejection controls for the external Apple Magic
Trackpad model 0265 and an optional typing guard for the saved Apple device group.
It also fixes the local guard's missing desktop-login startup configuration.

## Apple palm rejection

Open **Apple → Pointer → Palm rejection** to choose the system default or a
custom contact-size threshold. Lower thresholds reject smaller contacts but
can also interfere with fingers and gestures. The tested model's default is
900; 700 worked for one measured setup and is not a universal recommendation.

Install the helper from the installed plugin directory or a trusted checkout:

```sh
sudo install -Dm644 palm-system.py /usr/local/libexec/trackpad-plus-palm.py
```

Select the threshold, press **Apply palm settings**, and authorize the change.
Log out and back in to activate it. The panel reports pending changes and never
logs you out automatically. USB and Bluetooth use matching thresholds. The
helper backs up existing rules, preserves unrelated sections, and refuses
conflicting manual rules. **System default** removes the managed overrides.

The control is limited to model 0265; other Apple models and Dell pads retain
their native defaults. [Full instructions](README.md#apple-palm-rejection).

## Optional typing protection for external Apple trackpads

The external Magic Trackpad tested here does not support native
disable-while-typing, so the panel's switch alone does not suppress touches.
The bundled optional guard pauses the saved `apple` group during ordinary
physical-keyboard typing and resumes about 0.55 seconds after typing stops.
Ctrl, Alt, and Super shortcuts do not trigger the pause. No typed text is logged.

From the installed plugin directory or a trusted checkout:

```sh
install -Dm644 trackpad-typing-guard.py "$HOME/.local/lib/trackpad-typing-guard.py"
install -Dm644 trackpad-typing-guard.service "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/trackpad-typing-guard.service"
systemctl --user daemon-reload
systemctl --user enable --now trackpad-typing-guard.service
python3 "$HOME/.local/lib/trackpad-typing-guard.py" status
```

First connect and select the Apple pad in Trackpad Plus, and leave **Enable
trackpad** and **Disable While Typing** on. Keyboard device read access is
required. Verify a nonzero `keyboards` count, then type while touching the pad:
the pointer should pause and resume afterward. `pauses` and `resumes` should
increase. The enabled service returns at desktop login; merely starting it does
not persist protection after logout or reboot. It does not protect Dell or
separately saved built-in Apple groups.

Plugin installation does not automatically install this service. Repeat the
copy commands and restart the service when updating its separate copy.
[Verification, update, and removal instructions](README.md#optional-apple-typing-guard).

## Install or upgrade

New installation:

```sh
omarchy plugin add https://github.com/davefano/omarchy-trackpad-plus.git --enable
```

For an existing Git-managed copy, back up local edits and settings first:

```sh
trackpad_plugin="${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/davefano.trackpad-plus"
python3 "$trackpad_plugin/overview-control.py" stop
omarchy plugin update davefano.trackpad-plus
omarchy restart shell
```

Then open the installed directory to run either optional setup above:

```sh
cd "${XDG_CONFIG_HOME:-$HOME/.config}/omarchy/plugins/davefano.trackpad-plus"
```

Existing pointer and scrolling preferences remain saved. Optional palm settings
and the typing guard require their own setup. See the
[README](README.md#install-and-upgrade) for migration and rollback details.

## Verification

Regression coverage includes palm-rule validation, conflict handling and
preservation; typing pause/resume and shutdown restoration; and inclusion of
the guard and login-enabled service in an installation made from tracked files.
The typing guard was physically verified on a Dell XPS with an external Apple
Magic Trackpad. Other hardware needs its own typing test.
