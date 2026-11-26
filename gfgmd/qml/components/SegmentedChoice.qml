pragma ComponentBehavior: Bound
import QtQuick

// One choice of two or three, drawn as joined buttons (Video | Audio; This video | Whole playlist).
// The chosen one shows in the accent color. Screen readers hear radio buttons; Left and Right move
// between them, as in a radio group. `options` holds {label, code, icon}; `activated` fires
// for a new choice only.
Row {
    id: choice

    property var options: []
    property string value: ""
    property string accessibleName: ""
    // Shorter buttons, for a row of other compact controls.
    property bool compact: false

    signal activated(string code)

    function _choose(index) {
        var count = choice.options.length
        if (count === 0) return
        var wrapped = (index + count) % count
        var button = repeater.itemAt(wrapped) as AppButton
        if (button) button.forceActiveFocus(Qt.TabFocusReason)
        if (choice.options[wrapped].code !== choice.value) choice.activated(choice.options[wrapped].code)
    }

    spacing: 0
    Accessible.role: Accessible.Grouping
    Accessible.name: choice.accessibleName

    Repeater {
        id: repeater
        model: choice.options

        delegate: AppButton {
            id: segment
            required property var modelData
            required property int index

            compact: choice.compact
            text: segment.modelData.label
            iconName: segment.modelData.icon || ""
            checked: choice.value === segment.modelData.code
            flatLeft: segment.index > 0
            flatRight: segment.index < choice.options.length - 1
            // Only the chosen button is a Tab stop, as in a radio group.
            activeFocusOnTab: segment.checked || choice.options.every(option => option.code !== choice.value) && segment.index === 0
            Accessible.role: Accessible.RadioButton
            Accessible.checkable: true
            Accessible.checked: segment.checked
            Keys.onLeftPressed: choice._choose(segment.index - 1)
            Keys.onRightPressed: choice._choose(segment.index + 1)
            onClicked: if (!segment.checked) choice.activated(segment.modelData.code)
        }
    }
}
