pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import "Scroll.js" as Scroll

// Scroll feel: Linear, or a macOS profile's measured scrolling. Only Apply changes scrolling.
FocusScope {
  id: editor
  required property color foreground
  required property color accent
  required property string fontFamily
  property real uiScale: 1
  property var saved: ({ profile: "linear" })
  property var draft: Scroll.copy(saved)
  property string deviceLabel: "Trackpad"
  property bool busy: false
  property string settingsError: ""
  property bool canRestore: false
  // macOS profiles: rows from `trackpads.py profiles` for this trackpad.
  property var profiles: []
  property string profilesDirectory: ""
  property string profilesStatus: ""
  property bool drift: false
  // libinput applies a scroll curve only with a custom pointer curve: Pointer feel macOS or Custom.
  property bool pointerReady: true
  readonly property bool imported: draft.profile === "imported"
  readonly property var importedRow: imported && draft.imported ? rowFor(draft.imported) : null
  readonly property var speeds: Scroll.speeds(importedRow)
  readonly property bool dirty: !Scroll.same(draft, saved)
  readonly property bool canApply: dirty && !busy && (!imported || (!!draft.imported && pointerReady))
  signal applyRequested(var value)
  signal restoreRequested()
  signal backRequested()
  implicitHeight: contents.implicitHeight

  function begin() {
    forceActiveFocus()
    backButton.forceActiveFocus()
    draft = Scroll.copy(saved)
  }
  function choose(profile) {
    if (profile !== "imported") { draft = { profile: "linear" }; return }
    if (saved.profile === "imported") { draft = Scroll.copy(saved); return }
    var first = profiles.filter(Scroll.usable)[0]
    draft = { profile: "imported", imported: first ? Scroll.reference(first) : null }
  }
  function rowFor(imported) {
    for (var i = 0; i < profiles.length; i++)
      if (profiles[i].file === imported.file && profiles[i].sha256 === imported.sha256) return profiles[i]
    return null
  }
  // Choosing the applied file keeps its saved scrolling; Re-apply converts it for a new display.
  function chooseFile(row) {
    if (!Scroll.usable(row)) return
    var current = saved.profile === "imported" && saved.imported.file === row.file && saved.imported.sha256 === row.sha256
    draft = current ? Scroll.copy(saved) : { profile: "imported", imported: Scroll.reference(row) }
  }
  // Returning to the applied speed restores the saved scrolling, so nothing is left to apply.
  function setScrollSpeed(speed) {
    if (!importedRow) return
    var next = { profile: "imported", imported: Scroll.reference(importedRow, speed) }
    draft = Scroll.same(next, saved) ? Scroll.copy(saved) : next
  }
  function reapply() {
    var row = saved.imported ? rowFor(saved.imported) : null
    if (!row || busy) return
    draft = { profile: "imported", imported: Scroll.reference(row, saved.imported.scroll_speed) }
    applyRequested(Scroll.copy(draft))
  }
  function rowLabel(row) {
    if (row.error) return row.file + " · " + row.error
    if (!row.scroll) return row.name + " · no scrolling; export it again on its Mac"
    if (!row.scroll.measured) return row.name + " · run the scroll check on its Mac"
    if (row.scroll.error) return row.name + " · " + row.scroll.error
    return row.name
  }
  Keys.onEscapePressed: backRequested()

  component Label: Text {
    color: editor.foreground
    font.family: editor.fontFamily
    font.pixelSize: 13 * editor.uiScale
    wrapMode: Text.WordWrap
  }
  component Action: Button {
    id: control
    property bool selected: false
    implicitHeight: 34 * editor.uiScale
    font.family: editor.fontFamily
    font.pixelSize: 12 * editor.uiScale
    padding: 8 * editor.uiScale
    contentItem: Text {
      text: control.text
      font: control.font
      color: editor.foreground
      horizontalAlignment: Text.AlignHCenter
      verticalAlignment: Text.AlignVCenter
      elide: Text.ElideRight
      opacity: control.enabled ? 1 : 0.4
    }
    background: Rectangle {
      radius: 5 * editor.uiScale
      color: control.selected || control.hovered ? Qt.alpha(editor.accent, 0.18) : Qt.alpha(editor.foreground, 0.04)
      border.width: control.activeFocus || control.selected ? 2 : 1
      border.color: control.activeFocus || control.selected ? editor.accent : Qt.alpha(editor.foreground, 0.2)
      opacity: control.enabled ? 1 : 0.4
    }
  }

  Column {
    id: contents
    width: parent.width
    spacing: 12 * editor.uiScale

    Row {
      width: parent.width
      spacing: 12 * editor.uiScale
      Action { id: backButton; text: "‹ Back"; width: 70 * editor.uiScale; onClicked: editor.backRequested() }
      Column {
        width: parent.width - backButton.width - parent.spacing
        Label { text: "Scroll feel"; font.pixelSize: 18 * editor.uiScale; font.bold: true }
        Label { text: editor.deviceLabel; opacity: 0.65; width: parent.width; elide: Text.ElideRight; wrapMode: Text.NoWrap }
      }
    }

    Row {
      width: parent.width
      spacing: 5 * editor.uiScale
      Repeater {
        model: [{ id: "linear", name: "Linear" }, { id: "imported", name: "macOS" }]
        Action {
          required property var modelData
          objectName: "scrollChoice-" + modelData.id
          width: (contents.width - 5 * editor.uiScale) / 2
          text: modelData.name
          selected: editor.draft.profile === modelData.id
          onClicked: editor.choose(modelData.id)
        }
      }
    }

    Label {
      width: parent.width
      text: editor.imported
        ? "Apple's scroll acceleration while your fingers move, measured on that Mac. Glides after a flick still come from each app."
        : "Content moves with your fingers, scaled by Scroll Speed in the main panel."
      opacity: 0.8
      font.pixelSize: 12 * editor.uiScale
    }

    Column {
      objectName: "scrollImportedSection"
      width: parent.width
      spacing: 8 * editor.uiScale
      visible: editor.imported
      Label {
        objectName: "scrollNeedsPointer"
        visible: !editor.pointerReady
        width: parent.width
        text: "macOS scrolling needs Pointer feel macOS or Custom: libinput applies scroll curves only with a custom pointer curve."
        font.pixelSize: 11 * editor.uiScale
      }
      Label {
        objectName: "scrollDrift"
        visible: editor.drift && editor.saved.profile === "imported"
        width: parent.width
        text: editor.saved.imported && editor.rowFor(editor.saved.imported)
          ? "Display scale changed since this was applied."
          : "Display scale changed since this was applied, and its profile file has changed or is gone."
        font.pixelSize: 11 * editor.uiScale
      }
      Action {
        objectName: "reapplyScroll"
        visible: editor.drift && editor.saved.profile === "imported" && !!editor.saved.imported && !!editor.rowFor(editor.saved.imported)
        width: parent.width
        text: "Re-apply for this display"
        enabled: !editor.busy && editor.pointerReady
        onClicked: editor.reapply()
      }
      Label {
        visible: editor.profilesStatus !== ""
        width: parent.width
        text: editor.profilesStatus
        opacity: 0.7
        font.pixelSize: 11 * editor.uiScale
      }
      Label {
        objectName: "scrollProfilesEmpty"
        visible: editor.profiles.length === 0 && editor.profilesStatus === ""
        width: parent.width
        text: "No macOS profiles yet. On your Mac, export one and run the scroll check (tools/macos/README.md), then copy the .json file to "
          + (editor.profilesDirectory || "~/.config/trackpad-plus/profiles") + "."
        font.pixelSize: 11 * editor.uiScale
        opacity: 0.8
      }
      Repeater {
        model: editor.profiles
        Action {
          required property var modelData
          required property int index
          objectName: "scrollProfileRow" + index
          width: parent.width
          enabled: Scroll.usable(modelData)
          selected: !!editor.draft.imported && editor.draft.imported.file === modelData.file
            && editor.draft.imported.sha256 === modelData.sha256
          text: editor.rowLabel(modelData)
          onClicked: editor.chooseFile(modelData)
        }
      }
      Column {
        visible: editor.speeds.length > 1
        width: parent.width
        spacing: 2 * editor.uiScale
        Label {
          objectName: "scrollSpeedLabel"
          width: parent.width
          text: {
            var speed = editor.draft.imported ? editor.draft.imported.scroll_speed : 0
            var own = editor.importedRow && Math.abs(editor.importedRow.scroll.speed - speed) < 1e-9
            return "Scrolling speed · " + Number(speed.toFixed(4)) + (own ? " (that Mac's setting)" : "")
          }
          opacity: 0.7
          font.pixelSize: 11 * editor.uiScale
        }
        Slider {
          objectName: "scrollSpeed"
          width: parent.width
          from: 0
          to: Math.max(1, editor.speeds.length - 1)
          stepSize: 1
          snapMode: Slider.SnapAlways
          // The slider moves between Apple's stops and the Mac's own setting.
          value: {
            var speed = editor.draft.imported ? editor.draft.imported.scroll_speed : 0
            var best = 0
            for (var i = 1; i < editor.speeds.length; i++)
              if (Math.abs(editor.speeds[i] - speed) < Math.abs(editor.speeds[best] - speed)) best = i
            return best
          }
          Accessible.name: "Scrolling speed"
          onMoved: editor.setScrollSpeed(editor.speeds[Math.round(value)])
        }
        Item {
          width: parent.width
          height: slowLabel.implicitHeight
          Label { id: slowLabel; text: "Slow"; opacity: 0.65; font.pixelSize: 11 * editor.uiScale }
          Label { anchors.right: parent.right; text: "Fast"; opacity: 0.65; font.pixelSize: 11 * editor.uiScale }
        }
      }
    }

    Row {
      width: parent.width
      spacing: 8 * editor.uiScale
      Action {
        objectName: "applyScroll"
        text: editor.busy ? "Applying…" : "Apply & try"
        width: (parent.width - parent.spacing) / 2
        selected: true
        enabled: editor.canApply
        onClicked: editor.applyRequested(Scroll.copy(editor.draft))
      }
      Action {
        objectName: "restoreScroll"
        text: "Restore previous"
        width: (parent.width - parent.spacing) / 2
        enabled: editor.canRestore && !editor.busy
        onClicked: editor.restoreRequested()
      }
    }
    Label {
      width: parent.width
      objectName: "scrollStatus"
      text: editor.settingsError ? "Settings error: " + editor.settingsError : editor.busy ? "Applying scroll feel…"
        : editor.dirty ? "Preview · Apply to feel the change." : "Applied · scroll in any app to try it."
      opacity: 0.7
      font.pixelSize: 11 * editor.uiScale
    }
  }
}
