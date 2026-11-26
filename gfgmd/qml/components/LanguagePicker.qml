pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// The Subtitles choice: a box like the other dropdowns ("No subtitles", or "English, Urdu
// (automatic)") that opens a list of languages to tick. A video's own list comes grouped: the
// creator's subtitles, then the captions YouTube made from the video's speech, then its machine
// translations, folded under "More languages" with a search box. `model` holds {code, name, kind}
// (kind: creator, automatic, translated, or language for a plain list). Up and Down move through
// the list, Space or Enter ticks, Esc closes it.
Button {
    id: picker

    property var model: []
    // The ticked codes. A tick hands the new list to `edited`; the owner sets `codes` from it, so
    // a binding to the owner's list stays.
    property var codes: []
    property string accessibleName: "Subtitles"
    property string toolTipText: ""
    property string emptyText: "No subtitles"

    signal edited(var codes)

    property string _filter: ""
    property bool _showTranslated: false

    readonly property var _picked: picker.model.filter(item => picker.codes.indexOf(item.code) >= 0)
    readonly property string summary: {
        if (picker.codes.length === 0) return picker.emptyText
        var names = picker._picked.map(item => item.name)
        var known = picker._picked.map(item => item.code)
        names = names.concat(picker.codes.filter(code => known.indexOf(code) < 0))
        return names.length > 3 ? names.slice(0, 3).join(", ") + " and " + (names.length - 3) + " more" : names.join(", ")
    }
    readonly property int _translatedCount: picker.model.filter(item => item.kind === "translated").length

    function toggle(code) {
        var list = picker.codes.filter(item => item !== code)
        if (list.length === picker.codes.length) list.push(code)
        picker.edited(list)
    }

    // The list's rows: section headings, languages, and the fold for the machine translations.
    function _rows() {
        var text = picker._filter.trim().toLowerCase()
        function matches(item) {
            return text.length === 0 || item.name.toLowerCase().indexOf(text) >= 0 || item.code.toLowerCase().indexOf(text) >= 0
        }
        function languages(items) { return items.map(item => Object.assign({"type": "language"}, item)) }
        var rows = []
        var groups = [["creator", "From the creator"], ["automatic", "Made from the video's speech"], ["language", ""]]
        for (var i = 0; i < groups.length; ++i) {
            var items = picker.model.filter(item => item.kind === groups[i][0] && matches(item))
            if (items.length === 0) continue
            if (groups[i][1].length > 0) rows.push({"type": "header", "name": groups[i][1]})
            rows = rows.concat(languages(items))
        }
        var translated = picker.model.filter(item => item.kind === "translated" && matches(item))
        if (translated.length > 0) {
            if (text.length > 0) {
                rows.push({"type": "header", "name": "Translated automatically"})
                rows = rows.concat(languages(translated))
            } else {
                rows.push({"type": "fold", "name": "More languages (translated automatically)", "count": translated.length})
                if (picker._showTranslated) rows = rows.concat(languages(translated))
            }
        }
        return rows
    }

    function _activate(row) {
        if (row.type === "language") picker.toggle(row.code)
        else if (row.type === "fold") picker._showTranslated = !picker._showTranslated
    }

    implicitHeight: Theme.controlHeight
    implicitWidth: 200
    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    // The Material style sets each side's padding itself, which `padding` alone doesn't override.
    padding: 0
    leftPadding: 0
    rightPadding: 0
    topPadding: 0
    bottomPadding: 0
    topInset: 0
    bottomInset: 0
    leftInset: 0
    rightInset: 0
    font.family: Theme.fontFamily
    font.pixelSize: Theme.fontBody

    Accessible.role: Accessible.ComboBox
    Accessible.name: picker.accessibleName
    Accessible.description: picker.summary + (picker.toolTipText.length > 0 ? ". " + picker.toolTipText : "")

    ToolTip.visible: picker.toolTipText.length > 0 && !list.visible && (picker.hovered || picker.visualFocus)
    ToolTip.text: picker.toolTipText
    ToolTip.delay: 600
    ToolTip.timeout: picker.hovered ? -1 : Theme.focusTipTimeout

    onClicked: list.open()
    Keys.onDownPressed: list.open()
    Keys.onSpacePressed: list.open()

    contentItem: Text {
        textFormat: Text.PlainText
        leftPadding: 10
        rightPadding: 26
        text: picker.summary
        font: picker.font
        color: picker.enabled && picker.codes.length > 0 ? Theme.text : Theme.textMuted
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        Accessible.ignored: true
    }

    background: Rectangle {
        radius: Theme.radius
        color: !picker.enabled ? Theme.surfaceAlt : picker.hovered ? Theme.surfaceHover : Theme.surface
        border.width: picker.visualFocus ? 2 : 1
        border.color: picker.visualFocus ? Theme.focusRing : picker.enabled ? Theme.inputBorder : Theme.border
        Behavior on color { ColorAnimation { duration: Theme.motionFast } }
        Behavior on border.color { ColorAnimation { duration: Theme.motionFast } }

        Icon {
            x: parent.width - width - 10
            anchors.verticalCenter: parent.verticalCenter
            name: "chevronDown"
            size: Theme.iconXs
            color: Theme.textMuted
        }
    }

    Popup {
        id: list
        y: picker.height + 2
        width: Math.max(picker.width, 300)
        height: Math.min(column.implicitHeight + 2 * list.padding, 380)
        padding: 4
        margins: Theme.spaceSm
        focus: true
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

        onAboutToShow: {
            picker._filter = ""
            search.text = ""
            // Ticked translations stay in view.
            picker._showTranslated = picker._picked.some(item => item.kind === "translated")
            view.currentIndex = 0
        }
        onOpened: (picker._translatedCount > 0 ? search.input : view).forceActiveFocus()
        onClosed: picker.forceActiveFocus()

        background: Rectangle {
            radius: Theme.radius
            color: Theme.surface
            border.width: 1
            border.color: Theme.borderStrong
        }

        contentItem: ColumnLayout {
            id: column
            spacing: 4

            StyledTextField {
                id: search
                Layout.fillWidth: true
                Layout.margins: 4
                visible: picker._translatedCount > 0 || picker.model.length > 15
                placeholderText: "Search languages"
                accessibleName: "Search languages"
                input.onTextChanged: { picker._filter = search.text; view.currentIndex = 0 }
                input.Keys.onDownPressed: view.forceActiveFocus()
            }
            ListView {
                id: view
                Layout.fillWidth: true
                Layout.fillHeight: true
                Layout.preferredHeight: Math.min(contentHeight, 320)
                implicitHeight: contentHeight
                clip: true
                model: picker._rows()
                keyNavigationEnabled: true
                boundsBehavior: Flickable.StopAtBounds
                highlightMoveDuration: 0
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                Accessible.role: Accessible.List
                Accessible.name: picker.accessibleName

                Keys.onSpacePressed: picker._activate(view.model[view.currentIndex])
                Keys.onReturnPressed: picker._activate(view.model[view.currentIndex])
                Keys.onEnterPressed: picker._activate(view.model[view.currentIndex])
                Keys.onUpPressed: function (event) {
                    if (view.currentIndex === 0 && search.visible) search.input.forceActiveFocus()
                    else event.accepted = false
                }

                delegate: ItemDelegate {
                    id: row
                    required property var modelData
                    required property int index
                    readonly property bool isLanguage: row.modelData.type === "language"
                    readonly property bool ticked: row.isLanguage && picker.codes.indexOf(row.modelData.code) >= 0

                    width: view.width
                    height: row.modelData.type === "header" ? 26 : 32
                    focusPolicy: Qt.NoFocus
                    highlighted: view.currentIndex === row.index && view.activeFocus
                    enabled: row.modelData.type !== "header"
                    Accessible.role: row.isLanguage ? Accessible.CheckBox : row.modelData.type === "fold" ? Accessible.Button : Accessible.StaticText
                    Accessible.name: row.modelData.type === "fold"
                        ? row.modelData.name + ", " + row.modelData.count + (picker._showTranslated ? ", open" : ", closed")
                        : row.modelData.name
                    Accessible.checkable: row.isLanguage
                    Accessible.checked: row.ticked
                    onClicked: { view.currentIndex = row.index; picker._activate(row.modelData) }

                    contentItem: RowLayout {
                        spacing: Theme.spaceSm

                        Rectangle {
                            visible: row.isLanguage
                            Layout.leftMargin: Theme.spaceSm
                            Layout.preferredWidth: 18
                            Layout.preferredHeight: 18
                            radius: Theme.radius / 2
                            color: row.ticked ? Theme.accentFill : Theme.surface
                            border.width: row.ticked ? 0 : 1
                            border.color: Theme.inputBorder
                            Behavior on color { ColorAnimation { duration: Theme.motionFast } }
                            // As AppCheckBox: the tick grows into place.
                            Icon {
                                anchors.centerIn: parent
                                opacity: row.ticked ? 1 : 0
                                scale: row.ticked ? 1 : 0.4
                                name: "checkMark"
                                size: 12
                                color: Theme.textOnAccent
                                Behavior on opacity { NumberAnimation { duration: Theme.motionFast } }
                                Behavior on scale { NumberAnimation { duration: Theme.motionMedium; easing.type: Easing.OutBack } }
                            }
                        }
                        Icon {
                            visible: row.modelData.type === "fold"
                            Layout.leftMargin: Theme.spaceSm
                            name: picker._showTranslated ? "chevronDown" : "chevronRight"
                            size: Theme.iconXs
                            color: Theme.textMuted
                        }
                        Text {
                            textFormat: Text.PlainText
                            Layout.fillWidth: true
                            leftPadding: row.modelData.type === "header" ? Theme.spaceSm : 0
                            text: row.modelData.type === "fold" ? row.modelData.name + "  ·  " + row.modelData.count : row.modelData.name
                            font.family: Theme.fontFamily
                            font.pixelSize: row.modelData.type === "header" ? Theme.fontCaption : Theme.fontBody
                            font.weight: row.modelData.type === "header" ? Font.DemiBold : Font.Normal
                            color: row.modelData.type === "header" ? Theme.textMuted : Theme.text
                            elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                    background: Rectangle {
                        color: row.highlighted || (row.hovered && row.enabled) ? Theme.accentSoft : "transparent"
                        radius: Theme.radius
                        Behavior on color { ColorAnimation { duration: Theme.motionFast } }
                    }
                }
            }
        }
    }
}
