// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Dialogs
import QtQuick.Layouts

import "../components"
import "../components/ListMenu.js" as ListMenu

// Channels and playlists the app watches: their new uploads download on a schedule while the app
// runs (it keeps running in the tray). Import from YouTube Takeout, or back up and restore.
Item {
    id: page

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spaceXl
        spacing: Theme.spaceLg

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceSm

            AppButton {
                kind: "primary"
                text: "Subscribe"
                iconName: "add"
                onClicked: addDialog.open()
            }
            AppButton {
                text: "Check all now"
                iconName: "refresh"
                enabled: subscriptionsController.count > 0
                onClicked: subscriptionsController.checkAll()
            }
            Item { Layout.fillWidth: true }
            AppButton {
                kind: "ghost"
                text: "Import"
                iconName: "import"
                toolTipText: "Subscribe from a YouTube subscriptions export (Google Takeout) or a file saved by this app"
                onClicked: importDialog.open()
            }
            AppButton {
                kind: "ghost"
                text: "Export"
                iconName: "copy"
                enabled: subscriptionsController.count > 0
                onClicked: exportDialog.open()
            }
        }

        ListView {
            id: view
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: subscriptionsController.model
            spacing: 2
            boundsBehavior: Flickable.StopAtBounds
            keyNavigationEnabled: true
            activeFocusOnTab: true
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Accessible.role: Accessible.List
            Accessible.name: "Subscriptions"
            // Space turns watching on or off, Enter checks now, and the Menu key or Shift+F10 (a context-menu
            // request on Windows) opens the menu at the row.
            Keys.onSpacePressed: {
                var row = subscriptionsController.model.get(view.currentIndex)
                if (row.subId !== undefined) subscriptionsController.setEnabled(row.subId, !row.active)
            }
            Keys.onReturnPressed: {
                var row = subscriptionsController.model.get(view.currentIndex)
                if (row.subId !== undefined && !row.checking) subscriptionsController.checkNow(row.subId)
            }
            ContextMenu.onRequested: function (position) {
                var index = ListMenu.rowFor(view, position)
                if (index < 0) return
                view.currentIndex = index
                var row = subscriptionsController.model.get(index)
                if (row.subId !== undefined) subMenu.openFor(row.subId, row.url, row.autoDownload, view.currentItem)
            }

            delegate: Rectangle {
                id: sub
                required property int index
                required property int subId
                required property string title
                required property string url
                required property string site
                required property bool active
                required property bool autoDownload
                required property string intervalText
                required property string lastText
                required property string nextText
                required property string resultText
                required property bool failed
                required property int newCount
                required property bool checking

                width: view.width
                height: 72
                radius: Theme.radius
                color: subHover.hovered || ListView.isCurrentItem ? Theme.surfaceHover : "transparent"
                border.width: ListView.isCurrentItem && view.activeFocus ? 2 : 0
                border.color: Theme.focusRing
                Accessible.role: Accessible.ListItem
                Accessible.name: sub.title + ", " + sub.resultText
                HoverHandler { id: subHover }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spaceMd
                    anchors.rightMargin: Theme.spaceSm
                    spacing: Theme.spaceMd

                    AppSwitch {
                        checked: sub.active
                        accessibleName: "Watch " + sub.title
                        toolTipText: sub.active ? "Stop checking this subscription" : "Check this subscription again"
                        onToggled: subscriptionsController.setEnabled(sub.subId, checked)
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 3
                        Text {
                            textFormat: Text.PlainText
                            Layout.fillWidth: true
                            text: sub.title
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontBody
                            font.weight: Font.DemiBold
                            color: sub.active ? Theme.text : Theme.textMuted
                            elide: Text.ElideRight
                        }
                        Text {
                            textFormat: Text.PlainText
                            Layout.fillWidth: true
                            text: [sub.site, sub.intervalText,
                                   sub.lastText === "Never" ? "not checked yet" : "checked " + sub.lastText,
                                   sub.nextText === "Off" ? "not checking"
                                       : sub.nextText === "Never" ? "next check soon" : "next check " + sub.nextText,
                                   sub.checking ? "Checking..." : sub.resultText].filter(p => p.length > 0).join("  ·  ")
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontCaption
                            color: sub.failed
                                ? Theme.danger : Theme.textMuted
                            elide: Text.ElideRight
                        }
                    }
                    AppButton {
                        visible: sub.newCount > 0 && !sub.autoDownload
                        text: "Download " + sub.newCount + " new"
                        iconName: "download"
                        onClicked: subscriptionsController.downloadNew(sub.subId)
                    }
                    BusyIndicator { visible: sub.checking; running: visible; implicitWidth: 24; implicitHeight: 24 }
                    AppButton {
                        kind: "ghost"
                        compact: true
                        iconName: "refresh"
                        enabled: !sub.checking
                        toolTipText: "Check now"
                        onClicked: subscriptionsController.checkNow(sub.subId)
                    }
                    AppButton {
                        kind: "ghost"
                        compact: true
                        iconName: "more"
                        toolTipText: "More actions"
                        onClicked: subMenu.openFor(sub.subId, sub.url, sub.autoDownload)
                    }
                }
            }

            EmptyState {
                anchors.centerIn: parent
                visible: view.count === 0
                iconName: "bell"
                title: "No subscriptions yet"
                text: "Subscribe to a channel or playlist and its new uploads download on their own while the app "
                    + "runs. Turn on Start with Windows in Preferences to keep checking after a restart."
            }
        }
    }

    Shortcut { sequence: "F5"; enabled: page.visible; onActivated: subscriptionsController.checkAll() }

    AppMenu {
        id: subMenu
        property int subId: -1
        property string url: ""
        property bool auto: true
        function openFor(subId, url, auto, at) {
            subMenu.subId = subId
            subMenu.url = url
            subMenu.auto = auto
            subMenu.openAt(at || null)
        }
        AppMenuItem { text: "Open in browser"; onTriggered: appController.openUrl(subMenu.url) }
        AppMenuItem { text: "Copy link"; onTriggered: appController.copyText(subMenu.url) }
        AppMenuItem {
            text: subMenu.auto ? "Only tell me about new uploads" : "Download new uploads automatically"
            onTriggered: subscriptionsController.setAutoDownload(subMenu.subId, !subMenu.auto)
        }
        AppMenu {
            title: "Check"
            Repeater {
                model: prefsController.options.interval
                delegate: AppMenuItem {
                    required property var modelData
                    text: modelData.label
                    onTriggered: subscriptionsController.setInterval(subMenu.subId, modelData.code)
                }
            }
        }
        AppMenuSeparator {}
        AppMenuItem { text: "Unsubscribe (keep downloaded files)"; onTriggered: subscriptionsController.remove(subMenu.subId) }
    }

    AppDialog {
        id: addDialog
        title: "Subscribe to a channel or playlist"
        standardButtons: Dialog.Ok | Dialog.Cancel
        defaultButton: Dialog.Ok
        width: Math.min(page.width - 2 * Theme.spaceXl, 520)
        // Set while the dialog opens again over a link it couldn't take, which stays for fixing.
        property bool _again: false
        Component.onCompleted: addDialog.standardButton(Dialog.Ok).text = "Subscribe"
        onOpened: {
            if (addDialog._again) {
                addDialog._again = false
                link.selectInput()
                return
            }
            link.errorText = ""
            link.text = ""
            link.selectInput()
            interval.value = prefsController.value("subscriptions.interval_hours")
            saveAs.value = prefsController.value("downloads.kind") === "audio" ? "audio" : "video"
            existing.checked = false
            auto.checked = prefsController.value("subscriptions.auto_download")
        }
        onAccepted: {
            var problem = subscriptionsController.linkProblem(link.text)
            if (problem.length > 0) {
                link.errorText = problem
                addDialog._again = true
                // Opened again once this close is done; opening it from here is ignored while it closes.
                Qt.callLater(function () { addDialog.open() })
                return
            }
            // The new uploads download with the Video or Audio defaults in Preferences as they are now.
            subscriptionsController.add(link.text, {"kind": saveAs.value}, interval.currentValue, existing.checked,
                                        auto.checked)
        }

        ColumnLayout {
            width: parent.width
            spacing: Theme.spaceMd
            StyledTextField {
                id: link
                Layout.fillWidth: true
                label: "Channel or playlist link"
                placeholderText: "https://www.youtube.com/@channel"
                onTextChanged: link.errorText = ""
            }
            FormRow {
                Layout.fillWidth: true
                label: "Save as"
                labelWidth: 150
                SegmentedChoice {
                    id: saveAs
                    accessibleName: "Save new uploads as"
                    options: [
                        {"label": "Video", "code": "video", "icon": "video"},
                        {"label": "Audio", "code": "audio", "icon": "audio"}
                    ]
                    onActivated: function (code) { saveAs.value = code }
                }
            }
            FormRow {
                Layout.fillWidth: true
                label: "Check"
                labelWidth: 150
                StyledComboBox { id: interval; Layout.fillWidth: true; model: prefsController.options.interval; accessibleName: "How often to check" }
            }
            FormRow {
                Layout.fillWidth: true
                label: "Download automatically"
                labelWidth: 150
                AppSwitch { id: auto; accessibleName: "Download new uploads automatically" }
            }
            FormRow {
                Layout.fillWidth: true
                label: "Earlier uploads too"
                labelWidth: 150
                AppSwitch { id: existing; accessibleName: "Download earlier uploads too" }
            }
        }
    }

    FileDialog {
        id: importDialog
        title: "Import subscriptions"
        nameFilters: ["Subscriptions (*.csv *.json)", "All files (*)"]
        onAccepted: {
            var text = appController.readTextFile(selectedFile.toString())
            if (text.length === 0) return
            if (selectedFile.toString().toLowerCase().endsWith(".json")) subscriptionsController.importJson(text)
            else subscriptionsController.importTakeout(text)
        }
    }

    FileDialog {
        id: exportDialog
        title: "Export subscriptions"
        fileMode: FileDialog.SaveFile
        defaultSuffix: "json"
        nameFilters: ["Subscriptions (*.json)"]
        onAccepted: appController.writeTextFile(selectedFile.toString(), subscriptionsController.exportJson())
    }
}
