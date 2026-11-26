import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// The app's single button style: "primary", "secondary", "ghost", or "danger", with an optional
// icon. Icon-only buttons must set toolTipText, which also becomes their accessible name.
// Keyboard focus draws a visible ring (WCAG 2.4.7). A checked toggle shows on a tinted background
// and says so to screen readers; an icon-only one (Shuffle, Repeat) also turns its icon the accent
// color, while one with a label (Video | Audio, Smart Mode) keeps its label in the text color.
// Its colors fade between states and a press pushes it in slightly (Theme.motionFast).
Button {
    id: control

    property string kind: "secondary"
    property string iconName: ""
    property string toolTipText: ""
    property bool compact: false
    // Square corners on one side, where the button joins another (SegmentedChoice's buttons).
    property bool flatLeft: false
    property bool flatRight: false
    // Drawn in place of the font icon, for an icon that changes shape (Smart Mode's bulb lights up).
    property Component iconComponent: null
    // The background while checked; a warm tint suits Smart Mode's golden bulb.
    property color checkedTint: Theme.accentSoft

    readonly property bool _iconOnly: control.text.length === 0 && (control.iconName.length > 0 || control.iconComponent !== null)
    // Primary buttons are already accent-filled, so only the other kinds draw a checked state.
    readonly property bool _on: control.checked && control.kind !== "primary"
    readonly property color _fg: {
        if (!control.enabled) return Theme.textMuted
        if (control._on) return control._iconOnly ? Theme.accent : Theme.text
        switch (control.kind) {
        case "primary": return Theme.textOnAccent
        case "danger":  return Theme.danger
        case "ghost":   return Theme.text
        default:        return Theme.text
        }
    }

    implicitHeight: control.compact ? 28 : Theme.controlHeight
    implicitWidth: control._iconOnly
        ? implicitHeight
        : Math.max(implicitHeight, contentItem.implicitWidth + leftPadding + rightPadding)
    leftPadding: control._iconOnly ? 0 : (control.compact ? 10 : 14)
    rightPadding: control._iconOnly ? 0 : (control.compact ? 10 : 14)
    topPadding: 0
    bottomPadding: 0
    // The Material style insets the background 6 px top and bottom by default, which drew every
    // button 12 px shorter than its layout height (cramped pills, misaligned with text fields).
    topInset: 0
    bottomInset: 0
    leftInset: 0
    rightInset: 0
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontBody
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    scale: control.down ? 0.96 : 1
    Behavior on scale { NumberAnimation { duration: Theme.motionFast; easing.type: Easing.OutQuad } }

    ToolTip.visible: control.toolTipText.length > 0 && (control.hovered || control.visualFocus)
    ToolTip.text: control.toolTipText
    ToolTip.delay: 500
    ToolTip.timeout: control.hovered ? -1 : Theme.focusTipTimeout

    Accessible.role: Accessible.Button
    Accessible.name: control.text.length > 0 ? control.text : control.toolTipText
    Accessible.description: control.text.length > 0 ? control.toolTipText : ""
    Accessible.checkable: control.checkable
    Accessible.checked: control.checked

    contentItem: RowLayout {
        spacing: 6

        Icon {
            Layout.alignment: Qt.AlignVCenter
            Layout.fillWidth: control._iconOnly
            visible: control.iconName.length > 0 && control.iconComponent === null
            name: control.iconName
            size: control.compact ? Theme.iconSm : Theme.iconMd
            color: control._fg
            Behavior on color { ColorAnimation { duration: Theme.motionFast } }
        }
        Loader {
            Layout.alignment: Qt.AlignVCenter
            Layout.preferredWidth: control.compact ? Theme.iconSm : Theme.iconMd
            Layout.preferredHeight: control.compact ? Theme.iconSm : Theme.iconMd
            visible: control.iconComponent !== null
            active: control.iconComponent !== null
            sourceComponent: control.iconComponent
        }
        Text {
            textFormat: Text.PlainText
            Layout.alignment: Qt.AlignVCenter
            visible: control.text.length > 0
            text: control.text
            font: control.font
            color: control._fg
            Behavior on color { ColorAnimation { duration: Theme.motionFast } }
            elide: Text.ElideRight
            Accessible.ignored: true
        }
    }

    background: Rectangle {
        radius: Theme.radius
        topLeftRadius: control.flatLeft ? 0 : Theme.radius
        bottomLeftRadius: control.flatLeft ? 0 : Theme.radius
        topRightRadius: control.flatRight ? 0 : Theme.radius
        bottomRightRadius: control.flatRight ? 0 : Theme.radius
        color: {
            if (control.kind === "primary")
                return !control.enabled ? Theme.border : (control.down || control.hovered ? Theme.accentHover : Theme.accentFill)
            if (control.kind === "danger" && control.enabled && (control.hovered || control.down))
                return Theme.dangerSoft
            if (control.down) return Theme.border
            if (control._on && control.enabled) return control.checkedTint
            if (control.hovered && control.enabled) return Theme.surfaceHover
            return control.kind === "secondary" ? Theme.surface : "transparent"
        }
        Behavior on color { ColorAnimation { duration: Theme.motionFast } }
        border.width: control.kind === "secondary" ? 1 : 0
        border.color: Theme.border

        Rectangle {
            anchors.fill: parent
            anchors.margins: -3
            radius: Theme.radius + 3
            color: "transparent"
            border.width: 2
            border.color: Theme.focusRing
            visible: control.visualFocus
        }
    }
}
