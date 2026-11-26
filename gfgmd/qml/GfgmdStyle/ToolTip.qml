import QtQuick
import QtQuick.Templates as T
import "../components"

// Every tooltip in the app: the shared one behind each control's ToolTip.text, and ToolTip items such
// as the seek bar's time. A raised surface in the window's own theme (Material's is a light grey
// even in dark mode), just below the control, or above it where the window ends; long text wraps.
// Site titles show as they are, never as markup.
T.ToolTip {
    id: control

    // Long tooltips wrap at this width instead of spanning the window.
    readonly property int maxWidth: 320

    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? parent.height + 6 : 0

    implicitWidth: Math.min(control.maxWidth,
                            Math.max(implicitBackgroundWidth + leftInset + rightInset,
                                     implicitContentWidth + leftPadding + rightPadding))
    implicitHeight: Math.max(implicitBackgroundHeight + topInset + bottomInset,
                             implicitContentHeight + topPadding + bottomPadding)

    // Kept this far inside the window; past its bottom edge, the tooltip shows above the control.
    margins: 8
    topPadding: 5
    bottomPadding: 6
    leftPadding: 9
    rightPadding: 9
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontCaption

    closePolicy: T.Popup.CloseOnEscape | T.Popup.CloseOnPressOutsideParent | T.Popup.CloseOnReleaseOutsideParent

    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0.0; to: 1.0; duration: Theme.motionFast; easing.type: Easing.OutQuad }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1.0; to: 0.0; duration: Theme.motionFast; easing.type: Easing.InQuad }
    }

    contentItem: Text {
        text: control.text
        textFormat: Text.PlainText
        font: control.font
        wrapMode: Text.Wrap
        color: Theme.text
    }

    background: Item {
        // A soft edge under the card, so it lifts off whatever it covers.
        Rectangle {
            anchors.fill: parent
            anchors.topMargin: 1
            anchors.bottomMargin: -2
            anchors.leftMargin: -1
            anchors.rightMargin: -1
            radius: Theme.radius + 1
            color: Theme.toolTipShadow
        }
        Rectangle {
            anchors.fill: parent
            radius: Theme.radius
            color: Theme.toolTip
            border.width: 1
            border.color: Theme.toolTipBorder
        }
    }
}
