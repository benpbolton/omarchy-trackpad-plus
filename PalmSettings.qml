import QtQuick
import QtQuick.Controls

FocusScope {
  id: root
  property var settings: ({supported: false})
  property bool busy: false
  property bool loading: false
  property string error: ""
  property color foreground: "white"
  property color accent: "lightblue"
  property string fontFamily: "monospace"
  property int bodySize: 14
  property int captionSize: 12
  property real unit: 1
  property bool draftCustom: false
  property int draftThreshold: 700
  property bool dirty: false
  signal applyRequested(string threshold)
  signal editingFinished()
  Keys.onEscapePressed: editingFinished()
  readonly property bool changed: draftCustom !== (settings.mode === "custom")
    || (draftCustom && draftThreshold !== settings.threshold)
  implicitHeight: content.implicitHeight

  function acceptSettings(value) {
    settings = value
    if (!dirty) {
      draftCustom = value.mode === "custom"
      draftThreshold = value.threshold || 700
    }
  }

  function resetDraft() {
    dirty = false
    draftCustom = settings.mode === "custom"
    draftThreshold = settings.threshold || 700
  }

  function beginEditing() { customButton.forceActiveFocus() }

  Column {
    id: content
    width: parent.width
    spacing: 8 * root.unit
    Text {
      text: "Palm rejection"
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: root.bodySize
    }
    Text {
      width: parent.width
      text: "Apple Magic Trackpad · Bluetooth and USB"
      wrapMode: Text.WordWrap
      color: Qt.alpha(root.foreground, 0.65)
      font.family: root.fontFamily
      font.pixelSize: root.captionSize
    }
    Row {
      width: parent.width
      spacing: 6 * root.unit
      Button {
        id: defaultButton
        objectName: "palmDefault"
        width: (content.width - 6 * root.unit) / 2
        text: "System default"
        checked: !root.draftCustom
        checkable: true
        enabled: !root.busy
        onClicked: { root.dirty = true; root.draftCustom = false }
        Accessible.name: "Use system default palm rejection"
        contentItem: Text {
          text: defaultButton.text
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: root.bodySize
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
          color: Qt.alpha(root.foreground, defaultButton.checked ? 0.12 : 0.04)
          border.color: defaultButton.checked || defaultButton.activeFocus ? root.accent : Qt.alpha(root.foreground, 0.25)
        }
      }
      Button {
        id: customButton
        objectName: "palmCustom"
        width: (content.width - 6 * root.unit) / 2
        text: "Custom"
        checked: root.draftCustom
        checkable: true
        enabled: !root.busy
        onClicked: { root.dirty = true; root.draftCustom = true }
        Accessible.name: "Use custom palm rejection"
        contentItem: Text {
          text: customButton.text
          color: root.foreground
          font.family: root.fontFamily
          font.pixelSize: root.bodySize
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
        }
        background: Rectangle {
          color: Qt.alpha(root.foreground, customButton.checked ? 0.12 : 0.04)
          border.color: customButton.checked || customButton.activeFocus ? root.accent : Qt.alpha(root.foreground, 0.25)
        }
      }
    }
    Row {
      width: parent.width
      spacing: 8 * root.unit
      visible: root.draftCustom
      Text {
        width: parent.width - thresholdSpinner.width - 8 * root.unit
        anchors.verticalCenter: parent.verticalCenter
        text: "Contact-size threshold"
        wrapMode: Text.WordWrap
        color: root.foreground
        font.family: root.fontFamily
        font.pixelSize: root.captionSize
      }
      SpinBox {
        id: thresholdSpinner
        objectName: "palmThreshold"
        width: 110 * root.unit
        implicitHeight: 34 * root.unit
        leftPadding: 8 * root.unit
        rightPadding: 24 * root.unit
        from: 50
        to: 1020
        stepSize: 25
        value: root.draftThreshold
        editable: true
        live: true
        enabled: !root.busy
        wheelEnabled: false
        onValueModified: { root.dirty = true; root.draftThreshold = value }
        Accessible.name: "Apple palm contact-size threshold"
        font.family: root.fontFamily
        font.pixelSize: root.bodySize
        contentItem: TextInput {
          text: thresholdSpinner.textFromValue(thresholdSpinner.value, thresholdSpinner.locale)
          font: thresholdSpinner.font
          color: root.foreground
          selectionColor: root.accent
          selectedTextColor: "black"
          verticalAlignment: TextInput.AlignVCenter
          validator: thresholdSpinner.validator
          inputMethodHints: Qt.ImhDigitsOnly
          selectByMouse: true
          clip: true
        }
        background: Rectangle {
          color: Qt.alpha(root.foreground, 0.04)
          border.color: thresholdSpinner.activeFocus ? root.accent : Qt.alpha(root.foreground, 0.25)
        }
        up.indicator: Text {
          x: thresholdSpinner.width - width
          width: 22 * root.unit
          height: thresholdSpinner.height / 2
          text: "▴"
          color: root.foreground
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
          font.pixelSize: root.captionSize
        }
        down.indicator: Text {
          x: thresholdSpinner.width - width
          y: thresholdSpinner.height / 2
          width: 22 * root.unit
          height: thresholdSpinner.height / 2
          text: "▾"
          color: root.foreground
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
          font.pixelSize: root.captionSize
        }
      }
    }
    Text {
      width: parent.width
      text: "Lower values reject smaller palm touches. Too low can interfere with fingers and gestures. System default: 900."
      wrapMode: Text.WordWrap
      color: Qt.alpha(root.foreground, 0.65)
      font.family: root.fontFamily
      font.pixelSize: root.captionSize
    }
    Button {
      id: applyButton
      objectName: "palmApply"
      text: root.busy ? "Saving…" : "Apply palm settings"
      enabled: !root.busy && !root.loading && root.changed && root.settings.helper_installed === true
      onClicked: root.applyRequested(root.draftCustom ? String(root.draftThreshold) : "default")
      Accessible.name: "Apply Apple palm rejection settings"
      contentItem: Text {
        text: applyButton.text
        color: root.foreground
        opacity: applyButton.enabled ? 1 : 0.4
        font.family: root.fontFamily
        font.pixelSize: root.bodySize
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
      }
      background: Rectangle {
        color: Qt.alpha(root.foreground, 0.08)
        border.color: applyButton.activeFocus ? root.accent : Qt.alpha(root.foreground, 0.25)
      }
    }
    Text {
      width: parent.width
      text: root.error || (root.busy ? "Authorize the administrator prompt to save."
        : !root.settings.helper_installed ? "Install the palm settings helper to enable Apply."
        : root.settings.pending ? "Saved · Log out and back in to activate."
        : "Saved settings loaded when this desktop session started.")
      wrapMode: Text.WordWrap
      color: root.error ? root.accent : Qt.alpha(root.foreground, 0.75)
      font.family: root.fontFamily
      font.pixelSize: root.captionSize
    }
  }
}
