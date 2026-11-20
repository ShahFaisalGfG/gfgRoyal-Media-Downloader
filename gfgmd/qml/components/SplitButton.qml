import QtQuick
import QtQuick.Layouts

// A primary button with a cap on its right for more choices about the same action (Download, and
// its download options). The halves read as one control, with a hairline between them; each takes
// keyboard focus and lights up on its own. The cap's arrow points up while its choices show.
RowLayout {
    id: split

    property string text: ""
    property string iconName: ""
    property string toolTipText: ""
    // The cap's tooltip, which is also its accessible name.
    property string capToolTipText: ""
    // What a screen reader calls the arrow (it can say whether the options are open).
    property string capAccessibleName: ""
    property bool capOpen: false

    signal clicked()
    signal capClicked()

    spacing: 1  // the window shows through: the hairline between the halves

    AppButton {
        kind: "primary"
        flatRight: true
        text: split.text
        iconName: split.iconName
        toolTipText: split.toolTipText
        onClicked: split.clicked()
    }
    AppButton {
        Layout.preferredWidth: 30
        kind: "primary"
        flatLeft: true
        iconName: split.capOpen ? "chevronUp" : "chevronDown"
        toolTipText: split.capToolTipText
        Accessible.role: Accessible.ButtonDropDown
        Accessible.name: split.capAccessibleName || split.capToolTipText
        onClicked: split.capClicked()
    }
}
