pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// Combo box for {label, code} option lists. Bind `value` to the option it shows; the box follows
// it as it changes and flags a value missing from the list instead of silently showing another.
ComboBox {
    id: control

    property var value: undefined
    property string accessibleName: ""
    property string toolTipText: ""
    property string placeholderText: ""
    property bool mustChoose: false
    // When true, each item shows the icon of the app whose exe the code (a process name) maps to.
    property bool showIcons: false
    // Bumped by the owner when new icon paths are known, so the item icons re-request.
    property int iconsTag: 0
    readonly property bool valueMissing: control.value !== undefined && control.value !== null
        && control.placeholderText.length === 0 && control.count > 0 && control.indexOfValue(control.value) < 0
    readonly property bool choiceMissing: control.mustChoose && control.currentIndex < 0
    readonly property bool _warn: control.valueMissing || control.choiceMissing

    function selectCode(code) {
        var idx = control.indexOfValue(code)
        if (idx >= 0) control.currentIndex = idx
        else if (control.placeholderText.length > 0) control.currentIndex = -1
    }

    function _sync() {
        if (control.value !== undefined) control.selectCode(control.value)
    }

    onValueChanged: control._sync()
    onModelChanged: Qt.callLater(control._sync)
    onCountChanged: Qt.callLater(control._sync)
    Component.onCompleted: control._sync()

    textRole: "label"
    valueRole: "code"
    implicitHeight: Theme.controlHeight
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontBody
    hoverEnabled: true

    Accessible.name: control.accessibleName
    Accessible.description: control.toolTipText

    ToolTip.visible: control.toolTipText.length > 0 && !control.popup.visible && (control.hovered || control.visualFocus)
    ToolTip.text: (control.valueMissing ? "Your saved choice isn't available any more. Pick another.\n" : "")
        + (control.choiceMissing ? "Required. " : "")
        + control.toolTipText
    ToolTip.delay: 600
    ToolTip.timeout: control.hovered ? -1 : Theme.focusTipTimeout

    contentItem: RowLayout {
        id: displayRow
        spacing: Theme.spaceSm
        readonly property bool showsPlaceholder: control.currentIndex < 0 && control.placeholderText.length > 0

        // The selected app's icon, matching the icons in the dropdown list.
        Image {
            visible: control.showIcons && !displayRow.showsPlaceholder && status === Image.Ready
            Layout.leftMargin: 10
            Layout.preferredWidth: (control.showIcons && !displayRow.showsPlaceholder) ? 18 : 0
            Layout.preferredHeight: 18
            source: (control.showIcons && control.currentIndex >= 0)
                ? "image://appicon/" + control.currentValue + "?v=" + control.iconsTag : ""
            sourceSize: Qt.size(28, 28)
            fillMode: Image.PreserveAspectFit
            smooth: true
            cache: false
        }
        Text {
            textFormat: Text.PlainText
            Layout.fillWidth: true
            leftPadding: (control.showIcons && !displayRow.showsPlaceholder) ? 0 : 10
            rightPadding: control.indicator.width + 6
            text: displayRow.showsPlaceholder ? control.placeholderText : control.displayText
            font: control.font
            color: control.enabled && !displayRow.showsPlaceholder ? Theme.text : Theme.textMuted
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            Accessible.ignored: true
        }
    }

    indicator: Icon {
        x: control.width - width - 10
        y: (control.height - height) / 2
        name: "chevronDown"
        size: Theme.iconXs
        color: Theme.textMuted
    }

    background: Rectangle {
        radius: Theme.radius
        color: !control.enabled ? Theme.surfaceAlt : control.hovered ? Theme.surfaceHover : Theme.surface
        border.width: control.visualFocus || control._warn ? 2 : 1
        border.color: control.visualFocus ? Theme.focusRing
            : control._warn ? Theme.warning
            : control.enabled ? Theme.inputBorder : Theme.border
        Behavior on color { ColorAnimation { duration: Theme.motionFast } }
        Behavior on border.color { ColorAnimation { duration: Theme.motionFast } }
    }

    delegate: ItemDelegate {
        id: itemRow
        required property var modelData
        required property int index

        width: control.popup.width
        height: 34
        highlighted: control.highlightedIndex === itemRow.index
        Accessible.name: itemRow.modelData[control.textRole]

        contentItem: RowLayout {
            spacing: Theme.spaceSm

            Image {
                visible: control.showIcons && status === Image.Ready
                Layout.leftMargin: Theme.spaceSm
                Layout.preferredWidth: control.showIcons ? 18 : 0
                Layout.preferredHeight: 18
                source: control.showIcons
                    ? "image://appicon/" + itemRow.modelData[control.valueRole] + "?v=" + control.iconsTag : ""
                sourceSize: Qt.size(28, 28)
                fillMode: Image.PreserveAspectFit
                smooth: true
                cache: false
            }
            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                leftPadding: control.showIcons ? 0 : Theme.spaceSm
                text: itemRow.modelData[control.textRole]
                font: control.font
                color: Theme.text
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
            }
        }
        background: Rectangle {
            color: itemRow.highlighted ? Theme.accentSoft : "transparent"
            Behavior on color { ColorAnimation { duration: Theme.motionFast } }
        }
    }

    popup: Popup {
        y: control.height + 2
        width: Math.max(control.width, 220)
        implicitHeight: Math.min(contentItem.implicitHeight + 8, 320)
        padding: 4
        margins: Theme.spaceSm

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
        }

        background: Rectangle {
            radius: Theme.radius
            color: Theme.surface
            border.width: 1
            border.color: Theme.borderStrong
        }
    }
}
