const vm = require('node:vm');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const qml = fs.readFileSync(path.join(__dirname, 'Panel.qml'), 'utf8');

// Execute the real QML functions; callback ordering is controlled by each test.
function context() {
  const settings = { enabled: true, natural_scroll: false, tap_to_click: true,
    disable_while_typing: true, clickfinger_behavior: true, accel_profile: 'adaptive',
    scroll_factor: 0.2, sensitivity: 0.1 };
  const ctx = {
    devices: [
      { id: 'apple', label: 'Apple', connected: true, names: ['apple'], settings: { ...settings } },
      { id: 'dell', label: 'Dell', connected: true, names: ['dell'], settings: { ...settings, sensitivity: 0.3 } }
    ],
    selectedDevice: 'apple', pendingActions: [], settingsError: '',
    editGeneration: 0, stateGeneration: 0, refreshPending: false,
    actionProc: { running: false }, stateProc: { running: false }, backend: 'trackpads.py',
    Model: require('./Model.js'),
    Curve: require('./Curve.js'), previousFeels: {}, curveEditor: {},
    Scroll: require('./Scroll.js'), previousScrollFeels: {}, scrollFeelEditor: {}, editingScrollFeel: false, editingCurve: false,
    keyCatcher: { forceActiveFocus() {} },
    scrollDebounce: { running: false, stop() { this.running = false; } },
    pointerDebounce: { running: false, stop() { this.running = false; } }
  };
  vm.createContext(ctx);
  const functions = qml.match(/^  function \w+\([^\n]*\) \{[^\n]*\}$|^  function \w+\([^\n]*\) \{\n[\s\S]*?^  \}/gm);
  for (const source of functions) vm.runInContext(source, ctx);
  ctx.loadSelection();
  return ctx;
}

{
  const ctx = context();
  ctx.selectDevice('dell');
  ctx.actionProc.running = true;
  ctx.scrollDebounce.running = ctx.pointerDebounce.running = true;
  ctx.pendingScrollFactor = 0.6;
  ctx.pendingPointerSpeed = 0.8;
  ctx.selectDevice('apple');
  assert.equal(ctx.pendingActions.length, 2);
  assert.ok(ctx.pendingActions.every(x => x.device === 'dell'));
  assert.equal(ctx.pendingActions[0].value, 0.6);
  assert.equal(ctx.pendingActions[1].value, 0.8);
  assert.equal(ctx.pointerSpeed, 0.1);
  ctx.togglePointerAcceleration();
  assert.equal(ctx.pendingActions[2].device, 'apple');
  assert.equal(ctx.pendingActions[2].value, 'flat');
  ctx.selectDevice('dell');
  assert.equal(ctx.pointerAcceleration, true);
}

{
  const ctx = context();
  const oldRead = JSON.stringify({ devices: ctx.devices });
  ctx.refresh();
  ctx.toggleNaturalScroll();
  assert.equal(ctx.naturalScroll, true);
  ctx.actionProc.running = false;
  ctx.finishAction(0); // The old state process is still running.
  ctx.receiveState(oldRead);
  assert.equal(ctx.naturalScroll, true, 'late read must not revert the successful edit');
  ctx.stateProc.running = false;
  ctx.finishStateRead(0);
  assert.equal(ctx.stateProc.running, true, 'discarding a stale read must schedule a fresh read');
  ctx.receiveState(JSON.stringify({ devices: ctx.devices }));
  ctx.stateProc.running = false;
  ctx.finishStateRead(0);
  assert.equal(ctx.stateProc.running, false, 'a successful read must not poll in a tight loop');
  ctx.toggleNaturalScroll();
  assert.equal(JSON.parse(ctx.actionProc.command.at(-1)), false, 'next click must reverse the edit');
}

{
  const ctx = context();
  ctx.refresh();
  ctx.scrollDebounce.running = true;
  ctx.receiveState(JSON.stringify({ devices: ctx.devices }));
  ctx.stateProc.running = false;
  ctx.finishStateRead(0);
  assert.equal(ctx.stateProc.running, false, 'refresh must wait for pending slider edits');
  ctx.scrollDebounce.running = false;
  ctx.pendingScrollFactor = 0.7;
  ctx.commitScrollFactor();
  ctx.actionProc.running = false;
  ctx.finishAction(0);
  assert.equal(ctx.stateProc.running, true);
}

{
  const ctx = context();
  ctx.toggleNaturalScroll();
  ctx.togglePointerAcceleration();
  ctx.actionProc.running = false;
  ctx.finishAction(124);
  assert.match(ctx.settingsError, /Could not save/);
  assert.equal(ctx.actionProc.running, true, 'a timed-out write must release the next queued write');
  assert.equal(ctx.actionProc.command.at(-2), 'accel_profile');
  ctx.actionProc.running = false;
  ctx.finishAction(0);
  assert.equal(ctx.stateProc.running, true);
  ctx.stateProc.running = false;
  ctx.settingsError = '';
  ctx.finishStateRead(124);
  assert.match(ctx.settingsError, /Could not read/);
  assert.equal(ctx.stateProc.running, false, 'a failed read must not immediately retry forever');
  ctx.refresh();
  assert.equal(ctx.stateProc.running, true, 'a subsequent poll must recover after a read timeout');
}

{
  const ctx = context();
  const argv = ctx.bounded(0.05, ['python3', '-c', 'import time; time.sleep(60)']);
  const result = spawnSync(argv[0], Array.from(argv.slice(1)), { timeout: 4000 });
  assert.ifError(result.error);
  assert.equal(result.status, 124, 'the actual timeout wrapper must reap a stalled helper');
  assert.match(qml, /command: root\.bounded\(15, \["python3", root\.backend, "state"\]\)/);
  ctx.toggleNaturalScroll();
  assert.deepEqual(Array.from(ctx.actionProc.command.slice(0, 4)), ['timeout', '-k', '2', '10']);
}

{
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, 'manifest.json'), 'utf8'));
  assert.equal(manifest.id, 'davefano.trackpad-plus');
  assert.match(qml, /ipcTarget: "davefano\.trackpad-plus"/);
  assert.match(qml, /manageIpc: true/);
  assert.match(qml, /root\.receiveState\(String\(text\)\)/);
  assert.match(qml, /Qt\.callLater\(function\(\) \{ root\.finishStateRead\(code\) \}\)/);
  assert.match(qml, /Qt\.callLater\(function\(\) \{ root\.finishAction\(code\) \}\)/);
}
{
  const ctx = context();
  ctx.scrollDebounce.restart = function() { this.running = true; };
  ctx.setScrollFactor(0.05);
  ctx.focusSection = 'scroll';
  ctx.moveCursorH(-1);
  assert.equal(ctx.scrollFactor, 0.04);
  ctx.selectDevice('dell'); // Flush the precise value to the original device.
  assert.equal(JSON.parse(ctx.actionProc.command.at(-1)), 0.04);
  assert.equal(ctx.actionProc.command.at(-3), 'apple');
  assert.equal(ctx.scrollFactor, 0.2);
  ctx.setScrollFactor(0);
  assert.equal(ctx.scrollFactor, 0.01);
  ctx.setScrollFactor(0.056);
  assert.equal(ctx.scrollFactor, 0.06);
}

{
  const ctx = context();
  ctx.actionProc.running = true;
  const original = JSON.stringify(ctx.pointerFeel);
  ctx.applyPointerFeel({profile: 'custom', curve: ctx.Curve.defaults()});
  assert.equal(ctx.devices[0].settings.accel_profile, 'custom');
  assert.equal(ctx.pointerFeel.profile, 'custom');
  ctx.selectDevice('dell');
  assert.equal(ctx.pointerFeel.profile, 'adaptive');
  assert.equal(ctx.previousFeels.dell, undefined);
  assert.equal(ctx.pendingActions[0].device, 'apple');
  ctx.selectDevice('apple');
  ctx.restorePointerFeel();
  assert.equal(JSON.stringify(ctx.pointerFeel), original);
  assert.equal(ctx.pendingActions[1].value.profile, 'adaptive');
  assert.equal(ctx.devices[1].settings.accel_profile, 'adaptive');
}

{
  const ctx = context();
  ctx.previousFeels.apple = {profile: 'flat', curve: ctx.Curve.defaults()};
  ctx.loadSelection();
  assert.equal(ctx.previousFeels.apple, undefined, 'authoritative state clears stale undo');
  ctx.devices = [];
  ctx.loadSelection();
  assert.equal(ctx.deviceName, '', 'removed devices must not remain actionable');
  assert.equal(ctx.deviceConnected, false);
  const backendExpression = qml.match(/readonly property string backend: (.*)/)[1];
  ctx.Qt = {resolvedUrl: () => 'file:///tmp/plugin%20with%20spaces/trackpads.py'};
  assert.equal(vm.runInContext(backendExpression, ctx), '/tmp/plugin with spaces/trackpads.py');
}

// The former Mac-inspired preset is an ordinary curve, shown and undone as Custom.
{
  const Curve = require('./Curve.js');
  const curve = {precision: 0.2, start: 0.8, end: 2.8, fast: 1};
  const feel = Curve.fromSettings({accel_profile: 'custom', curve_preset: 'mac', curve});
  assert.equal(feel.profile, 'custom');
  assert.deepEqual(feel.curve, curve);
  assert.equal(Curve.label(feel), 'Custom');
  assert.ok(Curve.usesCurve('mac'), 'an earlier undo record still restores as a curve');
  const ctx = context();
  ctx.actionProc.running = true;
  ctx.previousFeels.apple = {profile: 'mac', curve};
  ctx.restorePointerFeel();
  assert.equal(ctx.devices[0].settings.accel_profile, 'custom');
  assert.equal(ctx.pointerFeel.profile, 'custom');
}

// macOS profiles: a previewed file is applied by reference and undone by its converted curve.
{
  const ctx = context();
  ctx.actionProc.running = true;
  const reference = {file: 'mac.json', sha256: 'a'.repeat(64), name: 'MacBook Pro (M1 Pro)', tracking_speed: 1.5};
  ctx.applyPointerFeel({profile: 'imported', curve: ctx.Curve.defaults(), imported: reference});
  assert.deepEqual(ctx.pendingActions[0].value.imported, {file: 'mac.json', sha256: 'a'.repeat(64), tracking_speed: 1.5},
    'the backend receives the file reference and tracking speed, not the display name');
  const settings = ctx.devices[0].settings;
  assert.equal(settings.accel_profile, 'custom');
  assert.equal(settings.curve_preset, 'imported');
  assert.equal(ctx.pointerFeel.profile, 'imported');
  assert.equal(ctx.Curve.label(ctx.pointerFeel), 'macOS · MacBook Pro (M1 Pro)');
  ctx.deviceSettingsOpen = false;
  ctx.activeTab = 'pointer';
  assert.ok(!ctx.navigationSections().includes('pointer'), 'Pointer Speed is hidden for an imported curve');
  ctx.pointerSpeed = 0.1;
  ctx.adjustPointerSpeed(0.2);
  assert.equal(ctx.pointerSpeed, 0.1);
  ctx.applyPointerFeel({profile: 'flat', curve: ctx.Curve.defaults()});
  assert.equal(settings.imported_curve, undefined, 'leaving the profile drops its local curve');
  assert.equal(settings.curve_preset, 'custom');
}

{
  const ctx = context();
  ctx.actionProc.running = true;
  const converted = {name: 'Mac', file: 'mac.json', sha256: 'b'.repeat(64), tracking_speed: 0.875,
    mm_per_point: 0.2, px_per_point: 1, devices: {apple: {units_per_mm: 98.65, step: 0.1, points: [0, 1]}}};
  ctx.devices[0].settings = {...ctx.devices[0].settings, accel_profile: 'custom', curve_preset: 'imported',
    curve: ctx.Curve.defaults(), imported_curve: converted};
  ctx.devices[0].imported_drift = true;
  ctx.loadSelection();
  assert.equal(ctx.pointerDrift, true);
  ctx.applyPointerFeel({profile: 'adaptive', curve: ctx.Curve.defaults()});
  assert.equal(ctx.pointerDrift, false, 'a new feel clears the drift notice locally');
  ctx.restorePointerFeel();
  assert.deepEqual(ctx.pendingActions[1].value.imported, converted, 'undo needs no profile file');
  assert.equal(ctx.devices[0].settings.curve_preset, 'imported');
  assert.ok(ctx.Curve.same(ctx.pointerFeel, {profile: 'imported', curve: ctx.Curve.defaults(),
    imported: {file: 'mac.json', sha256: 'b'.repeat(64), tracking_speed: 0.875}}), 'a reference equals its converted curve');
  assert.ok(!ctx.Curve.same(ctx.pointerFeel, {profile: 'imported', curve: ctx.Curve.defaults(),
    imported: {file: 'mac.json', sha256: 'b'.repeat(64), tracking_speed: 1}}), 'another tracking speed is a change');
}

{
  const ctx = context();
  ctx.profilesProc = {running: false};
  ctx.editingCurve = true;
  ctx.pointerProfiles = {loading: false, error: '', directory: '', profiles: []};
  ctx.profilesRequest = 0;
  ctx.refreshProfiles();
  assert.deepEqual(Array.from(ctx.profilesProc.command), ['timeout', '-k', '2', '15', 'python3', 'trackpads.py', 'profiles', 'apple']);
  const first = ctx.profilesProc.requestId;
  ctx.refreshProfiles();
  assert.equal(ctx.profilesPending, true, 'an overlapping open waits for the running read');
  ctx.profilesProc.running = false;
  ctx.finishProfiles(0, first);
  assert.equal(ctx.profilesProc.running, true);
  ctx.receiveProfiles(JSON.stringify({profiles: [{file: 'old.json'}]}), first);
  assert.equal(ctx.pointerProfiles.loading, true, 'a superseded reply is dropped');
  ctx.receiveProfiles(JSON.stringify({directory: '/p', profiles: [{file: 'new.json'}],
    context: {interfaces: {apple: {units_per_mm: 98.65}}, monitor: {name: 'eDP-1'}}}), ctx.profilesProc.requestId);
  assert.equal(ctx.pointerProfiles.profiles[0].file, 'new.json');
  assert.equal(ctx.pointerProfiles.device, 'apple');
  ctx.profilesProc.running = false;
  ctx.refreshProfiles();
  ctx.profilesProc.running = false;
  ctx.finishProfiles(124, ctx.profilesProc.requestId);
  assert.match(ctx.pointerProfiles.error, /Could not read pointer profiles/, 'a timed-out read reports an error');
}

{
  const Curve = require('./Curve.js');
  const curve = Curve.defaults();
  const samples = Curve.points(curve);
  for (let index = 0; index <= 160; index++) {
    assert.equal(Curve.sampledGain(curve, index / 40, samples), Curve.sampledGain(curve, index / 40));
  }
}

{
  const ctx = context();
  ctx.actionProc.running = true;
  for (let i = 0; i < 1000; i++) ctx.enqueue('scroll_factor', 0.01 + (i % 100) / 100);
  assert.equal(ctx.pendingActions.length, 1, 'repeated scalar updates should coalesce');
  assert.equal(ctx.pendingActions[0].value, 1);
  for (let i = 0; i < 200; i++) ctx.enqueue(i % 2 ? 'natural_scroll' : 'tap_to_click', true);
  assert.equal(ctx.pendingActions.length, 128, 'pending actions must have a fixed memory bound');
  assert.match(ctx.settingsError, /Too many/);
}

{
  const ctx = context();
  ctx.actionProc.running = true;
  ctx.scrollDebounce.running = true;
  ctx.pendingScrollFactor = 0.4;
  ctx.setScrollScale(3);
  assert.equal(ctx.pendingActions[0].option, 'scroll_factor');
  assert.equal(ctx.pendingActions[0].value, 0.4, 'pending edit must use its original scale');
  assert.equal(ctx.pendingActions[1].option, 'scroll_scale');
  assert.equal(ctx.pendingActions[1].value, 3);
  assert.equal(ctx.devices[0].settings.scroll_factor, 1.2);
  ctx.loadSelection();
  assert.ok(Math.abs(ctx.scrollFactor - 0.4) < 1e-9);
  ctx.pendingScrollFactor = 1;
  ctx.commitScrollFactor();
  assert.equal(ctx.pendingActions[2].value, 3, 'full slider reaches the configured scale');
  ctx.selectDevice('dell');
  assert.equal(ctx.scrollScale, 1);
  assert.equal(ctx.scrollFactor, 0.2);
  assert.equal(ctx.Model.clampScrollFactor(3), 1);
}

{
  const ctx = context();
  ctx.activeTab = "pointer";
  ctx.deviceSettingsOpen = false;
  assert.ok(ctx.navigationSections().includes("acceleration"));
  assert.ok(!ctx.navigationSections().includes("scroll"));
  ctx.activeTab = "scrolling";
  assert.ok(ctx.navigationSections().includes("scroll"));
  assert.ok(!ctx.navigationSections().includes("tap"));
  ctx.deviceSettingsOpen = true;
  assert.ok(ctx.navigationSections().includes("enable"));
  ctx.activeTab = "gestures";
  assert.ok(!ctx.navigationSections().includes("scroll"));
  ctx.scrollDebounce.running = true;
  ctx.pendingScrollFactor = 0.15;
  ctx.changeTab("pointer");
  assert.equal(ctx.activeTab, "pointer");
  assert.equal(ctx.scrollDebounce.running, false);
  assert.equal(JSON.parse(ctx.actionProc.command.at(-1)), 0.15);
}

{
  const ctx = context();
  ctx.gestureProc = {running: false};
  ctx.gestureBackend = 'gestures.py';
  ctx.gestureEditor = {load(value) { this.saved = value; }};
  ctx.runGestureAction('set', {enabled: true, fingers: 3, distance: 300, invert: false});
  assert.equal(ctx.gestureProc.running, true);
  assert.equal(ctx.gestureProc.command.at(-2), 'set');
  const before = JSON.stringify(ctx.gestureProc.command);
  ctx.runGestureAction('restore');
  assert.equal(JSON.stringify(ctx.gestureProc.command), before, 'busy gesture writes cannot overlap');
  ctx.finishGestureAction(124);
  assert.match(ctx.gestureError, /did not complete/);
  ctx.gestureProc.running = false;
  ctx.refreshGestures();
  assert.equal(ctx.gestureProc.command.at(-1), 'state');
  ctx.receiveGestures(JSON.stringify({can_edit: true, can_restore: true,
    settings: {enabled: true, fingers: 4, distance: 400, invert: false}, message: 'Managed'}));
  assert.equal(ctx.gestureEditor.saved.fingers, 4);
  assert.equal(ctx.gestureCanRestore, true);
  ctx.finishGestureAction(0);
  assert.equal(ctx.gestureError, '');
  ctx.receiveGestures('{"error":"reload rejected"}');
  assert.equal(ctx.gestureEditor.saved.fingers, 4, 'failed save must retain previous acknowledged settings');
  assert.match(ctx.gestureError, /reload rejected/);
}

// Explicit overview checks cannot discard unsaved gesture edits or accept old responses.
{
  const ctx = context();
  ctx.gestureProc = {running: false};
  ctx.overviewProc = {running: false};
  ctx.overviewRequest = 0;
  ctx.gestureBackend = 'gestures.py';
  ctx.gestureEditor = {draft: {fingers: 4, overview_provider: 'trackpad-plus'},
    load() { throw new Error('preview must not reload the draft'); }};
  ctx.requestOverview(true);
  const request = ctx.overviewRequest;
  assert.equal(ctx.overviewProc.command.at(-1), 'preview');
  ctx.requestOverview(false);
  assert.equal(ctx.overviewRequest, request, 'preview operations cannot overlap');
  ctx.receiveOverview(JSON.stringify({installed: true, reachable: true, protocolCompatible: true,
    rendered: false, opened: true, lockState: 'unlocked'}), request);
  assert.match(ctx.overviewPreviewText, /rendering is not confirmed/);
  assert.equal(ctx.gestureEditor.draft.fingers, 4);
  const status = ctx.overviewPreviewText;
  ctx.receiveOverview('{"error":"stale error"}', request - 1);
  ctx.finishOverview(124, request - 1);
  assert.equal(ctx.overviewPreviewText, status);
  ctx.overviewProc.running = false;
  ctx.requestOverview(false);
  assert.equal(ctx.overviewProc.command.at(-1), 'overview-status');
  ctx.finishOverview(124, ctx.overviewRequest);
  assert.match(ctx.overviewPreviewText, /did not respond/);
  ctx.receiveOverview(JSON.stringify({installed: true, reachable: true, protocolCompatible: true,
    rendered: true, opened: true, lockState: 'unlocked'}), ctx.overviewRequest);
  assert.match(ctx.overviewPreviewText, /rendered/);
  assert.equal(ctx.gestureEditor.draft.overview_provider, 'trackpad-plus');
}

// Gesture tab focus must not disable the panel's keyboard dispatcher until
// a control inside the editor actually owns focus.
{
  const ctx = context();
  let entered = 0, panelFocused = 0;
  ctx.gestureEditor = {activeFocus: false, beginEditing() { entered++; this.activeFocus = true; }};
  ctx.keyCatcher = {forceActiveFocus() { panelFocused++; ctx.gestureEditor.activeFocus = false; }};
  ctx.gestureProc = {running: false};
  ctx.gestureBackend = 'gestures.py';
  ctx.editingCurve = false;
  ctx.deviceSettingsOpen = false;
  ctx.activeTab = 'gestures';
  ctx.focusSection = 'device';
  assert.equal(ctx.keyboardNavigationBlocked(), false, 'reopened gesture tab must accept Escape and arrows');
  ctx.allSections = ctx.navigationSections();
  ctx.moveCursor(1);
  assert.equal(ctx.focusSection, 'device-settings');
  ctx.moveCursor(1);
  assert.equal(ctx.focusSection, 'tabs');
  ctx.moveCursor(1);
  assert.equal(entered, 1, 'Down from tabs enters the gesture controls');
  assert.equal(ctx.keyboardNavigationBlocked(), true, 'editor owns its keyboard input');
  ctx.changeTab('gestures');
  assert.equal(panelFocused, 1, 'mouse or keyboard tab selection restores panel navigation');
  assert.equal(ctx.keyboardNavigationBlocked(), false);
  ctx.activateCursor();
  assert.equal(entered, 2, 'Enter from tabs also enters the gesture controls');
  ctx.changeTab('pointer');
  assert.equal(ctx.keyboardNavigationBlocked(), false);
  ctx.activateCursor();
  assert.equal(entered, 2, 'other tabs retain existing navigation');
  ctx.editingCurve = true;
  assert.equal(ctx.keyboardNavigationBlocked(), true, 'curve editor keeps its existing focus behavior');
}

// macOS scrolling: references go to the backend, converted records come back for undo.
{
  const ctx = context();
  ctx.actionProc.running = true;
  ctx.devices[0].settings.accel_profile = 'custom';
  ctx.loadSelection();
  assert.deepEqual(ctx.scrollFeel, {profile: 'linear'});
  const reference = {file: 'mac.json', sha256: 'a'.repeat(64), name: 'MacBook Pro (M1 Pro)', scroll_speed: 1.5};
  ctx.applyScrollFeel({profile: 'imported', imported: reference});
  ctx.applyScrollFeel({profile: 'imported', imported: {...reference, scroll_speed: 2}});
  assert.equal(ctx.pendingActions.length, 2, 'scroll feel edits are never merged, so undo order holds');
  assert.deepEqual(ctx.pendingActions[0].value, {profile: 'imported',
    imported: {file: 'mac.json', sha256: 'a'.repeat(64), scroll_speed: 1.5}},
    'the backend receives the file reference and scrolling speed, not the display name');
  const settings = ctx.devices[0].settings;
  assert.equal(settings.scroll_preset, 'imported');
  assert.equal(settings.scroll_factor, 0.2, 'the Linear scroll factor is kept');
  assert.equal(ctx.scrollFeel.profile, 'imported');
  assert.equal(ctx.Scroll.label(ctx.scrollFeel), 'macOS · MacBook Pro (M1 Pro)');
  ctx.deviceSettingsOpen = false;
  ctx.activeTab = 'scrolling';
  assert.deepEqual(Array.from(ctx.navigationSections().slice(-2)), ['scroll-feel', 'natural'],
    'Scroll Speed is hidden for macOS scrolling; Natural scrolling stays');
  ctx.applyScrollFeel({profile: 'linear'});
  assert.equal(settings.imported_scroll, undefined, 'Linear drops the local scrolling');
  assert.equal(settings.scroll_preset, undefined);
  assert.deepEqual(Array.from(ctx.navigationSections().slice(-3)), ['scroll-feel', 'scroll', 'natural']);
}

{
  const ctx = context();
  ctx.actionProc.running = true;
  const converted = {name: 'Mac', file: 'mac.json', sha256: 'b'.repeat(64), scroll_speed: 0.3125,
    mm_per_point: 0.2, px_per_point: 1, devices: {apple: {units_per_mm: 98.65, step: 0.1, points: [0, 1]}},
    model: {curve: {}, resolution: 400, report_rate_hz: 67, driver: {}}};
  ctx.devices[0].settings = {...ctx.devices[0].settings, accel_profile: 'custom', scroll_preset: 'imported',
    imported_scroll: converted};
  ctx.devices[0].imported_scroll_drift = true;
  ctx.devices[0].previous_scroll_feel = {profile: 'linear'};
  ctx.loadSelection();
  assert.equal(ctx.scrollDrift, true);
  assert.deepEqual(ctx.previousScrollFeels.apple, {profile: 'linear'});
  ctx.applyScrollFeel({profile: 'linear'});
  assert.equal(ctx.scrollDrift, false, 'a new feel clears the drift notice locally');
  ctx.restoreScrollFeel();
  assert.deepEqual(ctx.pendingActions[1].value.imported, converted, 'undo needs no profile file');
  assert.equal(ctx.devices[0].settings.scroll_preset, 'imported');
  assert.ok(ctx.Scroll.same(ctx.scrollFeel, {profile: 'imported',
    imported: {file: 'mac.json', sha256: 'b'.repeat(64), scroll_speed: 0.3125}}), 'a reference equals its converted scrolling');
  assert.ok(!ctx.Scroll.same(ctx.scrollFeel, {profile: 'imported',
    imported: {file: 'mac.json', sha256: 'b'.repeat(64), scroll_speed: 1}}), 'another scrolling speed is a change');
  ctx.devices[0].settings.accel_profile = 'flat';
  ctx.devices[0].imported_scroll_inactive = true;
  ctx.loadSelection();
  assert.equal(ctx.scrollInactive, true, 'System or Flat pointer feel leaves macOS scrolling inactive');
  ctx.editingScrollFeel = true;
  assert.equal(ctx.keyboardNavigationBlocked(), true, 'the scroll feel editor owns its keyboard input');
}

// macOS Scrolling speed on the main tab: Apple's stops, applied as a new file reference.
{
  const ctx = context();
  ctx.actionProc.running = true;
  const converted = {name: 'Mac', file: 'mac.json', sha256: 'd'.repeat(64), scroll_speed: 0.3125, mac_speed: 0.3125,
    speeds: [0, 0.125, 0.3125, 0.5, 1, 3], mm_per_point: 0.2, px_per_point: 1,
    devices: {apple: {units_per_mm: 98.65, step: 0.1, points: [0, 1]}},
    model: {curve: {}, resolution: 400, report_rate_hz: 67, driver: {}}};
  ctx.devices[0].settings = {...ctx.devices[0].settings, accel_profile: 'custom', scroll_preset: 'imported',
    imported_scroll: converted};
  ctx.loadSelection();
  ctx.deviceSettingsOpen = false;
  ctx.activeTab = 'scrolling';
  assert.deepEqual(Array.from(ctx.navigationSections().slice(-3)), ['scroll-feel', 'scroll-speed', 'natural']);
  assert.equal(ctx.scrollSpeedStop(), 2);
  assert.equal(ctx.scrollSpeedText(2), '0.3125 · Mac default');
  assert.equal(ctx.scrollSpeedText(1), '0.125');
  ctx.focusSection = 'scroll-speed';
  ctx.moveCursorH(-1);
  assert.deepEqual(ctx.pendingActions[0].value, {profile: 'imported',
    imported: {file: 'mac.json', sha256: 'd'.repeat(64), scroll_speed: 0.125}}, 'a speed change converts the file again');
  const local = ctx.devices[0].settings.imported_scroll;
  assert.equal(local.scroll_speed, 0.125);
  assert.deepEqual(local.speeds, converted.speeds, 'the stops stay while the conversion runs');
  assert.equal(local.devices, undefined, "the old speed's curve is not kept for the new one");
  assert.equal(ctx.scrollSpeedStop(), 1);
  ctx.setScrollSpeedStop(1);
  assert.equal(ctx.pendingActions.length, 1, 'the applied stop is not sent again');
  ctx.setScrollSpeedStop(99);
  assert.equal(ctx.pendingActions[1].value.imported.scroll_speed, 3, 'stops are clamped');
  ctx.restoreScrollFeel();
  assert.equal(ctx.pendingActions[2].value.imported.scroll_speed, 0.125, 'undo returns to the previous speed');
}

{
  const Scroll = require('./Scroll.js');
  const row = {file: 'mac.json', sha256: 'c'.repeat(64), name: 'Mac',
    scroll: {speed: 0.3125, measured: true, speeds: [0, 0.125, 0.5, 1, 3]}};
  assert.deepEqual(Scroll.speeds(row), [0, 0.125, 0.3125, 0.5, 1, 3], "the Mac's own speed joins Apple's stops");
  assert.deepEqual(Scroll.speeds({...row, scroll: {...row.scroll, speed: 1}}), [0, 0.125, 0.5, 1, 3]);
  assert.ok(Scroll.usable(row));
  for (const bad of [{...row, error: 'x'}, {...row, scroll: undefined}, {...row, scroll: {...row.scroll, measured: false}},
                     {...row, scroll: {...row.scroll, error: 'too fast'}}])
    assert.ok(!Scroll.usable(bad));
  assert.deepEqual(Scroll.reference(row), {file: 'mac.json', sha256: 'c'.repeat(64), name: 'Mac', scroll_speed: 0.3125});
}

// Keep the inherited device parser usable for Intel Mac installations.
{
  const model = require('./Model.js');
  for (const name of ['bcm5974', 'apple-spi-trackpad', 'apple-mtp-multi-touch'])
    assert.equal(model.parseTouchpadDevice(JSON.stringify({mice: [{name}]})), name);
  assert.equal(model.parseTouchpadDevice(JSON.stringify({mice: [{name: 'bcm5974-mouse'}]})), '');
}
console.log('Passed: device selection, fine scroll steps, scroll feel, stale-read rejection, debounce ordering, timeout recovery, and IPC configuration.');
