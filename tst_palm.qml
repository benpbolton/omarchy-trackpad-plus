import QtQuick
import QtTest

Item {
  width: 380
  height: 700
  PalmSettings { id: editor; width: 340 }
  SignalSpy { id: applySpy; target: editor; signalName: "applyRequested" }
  TestCase {
    name: "PalmSettings"
    when: windowShown
    function init() {
      editor.busy = false
      editor.loading = false
      editor.dirty = false
      editor.error = ""
      editor.acceptSettings({supported: true, mode: "custom", threshold: 700, helper_installed: true, pending: true})
      applySpy.clear()
    }
    function test_existing_trial_is_loaded_without_another_apply() {
      compare(editor.draftThreshold, 700)
      compare(editor.draftCustom, true)
      verify(!findChild(editor, "palmApply").enabled)
    }
    function test_restore_system_default_emits_default_not_900_override() {
      mouseClick(findChild(editor, "palmDefault"))
      mouseClick(findChild(editor, "palmApply"))
      compare(applySpy.count, 1)
      compare(applySpy.signalArguments[0][0], "default")
    }
    function test_threshold_edit_survives_polling_and_applies_exact_value() {
      var spinner = findChild(editor, "palmThreshold")
      spinner.forceActiveFocus()
      keyClick(Qt.Key_Up)
      compare(editor.draftThreshold, 725)
      editor.acceptSettings({supported: true, mode: "custom", threshold: 700, helper_installed: true})
      compare(editor.draftThreshold, 725)
      mouseClick(findChild(editor, "palmApply"))
      compare(applySpy.signalArguments[0][0], "725")
    }
    function test_busy_prevents_multiple_requests() {
      mouseClick(findChild(editor, "palmDefault"))
      editor.busy = true
      verify(!findChild(editor, "palmApply").enabled)
      verify(!findChild(editor, "palmCustom").enabled)
    }
    function test_visual_layout() {
      verify(editor.implicitHeight < 700)
      var saved = false
      editor.grabToImage(function(result) {
        saved = result.saveToFile("/tmp/trackpad-palm-settings-preview.png")
      })
      tryVerify(function() { return saved })
    }
    function test_apply_is_disabled_during_background_read() {
      mouseClick(findChild(editor, "palmDefault"))
      editor.loading = true
      verify(!findChild(editor, "palmApply").enabled)
      mouseClick(findChild(editor, "palmApply"))
      compare(applySpy.count, 0)
      editor.loading = false
      mouseClick(findChild(editor, "palmApply"))
      compare(applySpy.count, 1)
    }
  }
}
