import QtQuick
import QtTest
import "Scroll.js" as Scroll

Rectangle {
  id: root
  width: 470
  height: 620
  color: "#171b22"
  ScrollFeelEditor {
    id: editor
    x: 20
    y: 20
    width: 430
    foreground: "#e7edf4"
    accent: "#82b8b0"
    fontFamily: "sans-serif"
    onApplyRequested: function(value) { saved = Scroll.copy(value) }
  }
  SignalSpy { id: applied; target: editor; signalName: "applyRequested" }
  SignalSpy { id: restored; target: editor; signalName: "restoreRequested" }
  SignalSpy { id: back; target: editor; signalName: "backRequested" }
  readonly property var macRow: ({ file: "mac.json", sha256: "a".repeat(64), name: "MacBook Pro (M1 Pro)",
    scroll: { speed: 0.3125, measured: true, speeds: [0, 0.125, 0.5, 0.6875, 0.875, 1, 1.5, 2, 2.5, 3] } })
  TestCase {
    name: "ScrollFeelEditor"
    when: windowShown
    function init() {
      editor.saved = { profile: "linear" }
      editor.busy = false
      editor.settingsError = ""
      editor.canRestore = false
      editor.profiles = []
      editor.profilesStatus = ""
      editor.drift = false
      editor.pointerReady = true
      editor.begin()
      applied.clear(); restored.clear(); back.clear()
    }
    function test_macos_picks_the_first_measured_profile_at_its_own_speed() {
      editor.profiles = [{ file: "old.json", sha256: "b".repeat(64), name: "Old Mac" },
        { file: "unmeasured.json", sha256: "c".repeat(64), name: "Air", scroll: { speed: 0.5, measured: false, speeds: [0, 1] } },
        root.macRow]
      mouseClick(findChild(editor, "scrollChoice-imported"))
      compare(editor.draft.imported.file, "mac.json")
      compare(editor.draft.imported.scroll_speed, 0.3125)
      verify(!findChild(editor, "scrollProfileRow0").enabled)
      verify(findChild(editor, "scrollProfileRow0").text.indexOf("export it again") >= 0)
      verify(findChild(editor, "scrollProfileRow1").text.indexOf("scroll check") >= 0)
      verify(findChild(editor, "scrollProfileRow2").selected)
      compare(editor.speeds.length, 11)
      compare(findChild(editor, "scrollSpeed").value, 2)
      verify(findChild(editor, "scrollSpeedLabel").text.indexOf("0.3125 (that Mac's setting)") >= 0)
    }
    function test_speed_slider_apply_and_return_to_the_saved_speed() {
      editor.profiles = [root.macRow]
      editor.choose("imported")
      var slider = findChild(editor, "scrollSpeed")
      slider.value = 7
      slider.moved()
      compare(editor.draft.imported.scroll_speed, 1.5)
      verify(editor.dirty)
      mouseClick(findChild(editor, "applyScroll"))
      compare(applied.count, 1)
      compare(applied.signalArguments[0][0].imported.scroll_speed, 1.5)
      verify(!editor.dirty)
      slider.value = 2
      slider.moved()
      verify(editor.dirty)
      slider.value = 7
      slider.moved()
      verify(!editor.dirty, "returning to the applied speed leaves nothing to apply")
      verify(findChild(editor, "scrollStatus").text.indexOf("Applied") >= 0)
    }
    function test_macos_needs_a_custom_pointer_curve() {
      editor.profiles = [root.macRow]
      editor.pointerReady = false
      editor.choose("imported")
      verify(findChild(editor, "scrollNeedsPointer").visible)
      verify(!findChild(editor, "applyScroll").enabled)
      editor.choose("linear")
      verify(!findChild(editor, "scrollNeedsPointer").visible)
    }
    function test_linear_restore_back_and_errors() {
      editor.profiles = [root.macRow]
      editor.saved = { profile: "imported", imported: Scroll.reference(root.macRow) }
      editor.canRestore = true
      editor.begin()
      verify(!findChild(editor, "applyScroll").enabled)
      mouseClick(findChild(editor, "scrollChoice-linear"))
      verify(findChild(editor, "applyScroll").enabled)
      mouseClick(findChild(editor, "restoreScroll"))
      compare(restored.count, 1)
      editor.settingsError = "Compositor unavailable"
      verify(findChild(editor, "scrollStatus").text.indexOf("Compositor unavailable") >= 0)
      editor.busy = true
      verify(!findChild(editor, "applyScroll").enabled)
      keyClick(Qt.Key_Escape)
      compare(back.count, 1)
    }
    function test_drift_offers_reapply_for_the_saved_file() {
      editor.profiles = [root.macRow]
      editor.saved = { profile: "imported", imported: Scroll.reference(root.macRow, 1.5) }
      editor.drift = true
      editor.begin()
      verify(findChild(editor, "scrollDrift").visible)
      wait(50) // let the newly visible button take its place
      mouseClick(findChild(editor, "reapplyScroll"))
      compare(applied.count, 1)
      compare(applied.signalArguments[0][0].imported.scroll_speed, 1.5)
      editor.profiles = []
      verify(!findChild(editor, "reapplyScroll").visible)
      verify(findChild(editor, "scrollDrift").text.indexOf("changed or is gone") >= 0)
    }
    function test_empty_profiles_explain_the_mac_steps() {
      editor.choose("imported")
      verify(findChild(editor, "scrollProfilesEmpty").visible)
      verify(!findChild(editor, "applyScroll").enabled)
    }
  }
}
