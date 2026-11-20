// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import "components"
import "pages"

// The main window: four pages (Downloads, Library, Subscriptions, Sign-ins) over the audio player and
// the run bar.
// Links dropped anywhere on the window are downloaded; closing keeps the app in the tray when that
// is on, so subscriptions and downloads carry on.
AppWindow {
    id: mainWin

    width: 1100
    height: 720
    minimumWidth: 820
    minimumHeight: 560
    // Starts hidden; app.py shows it after load unless it starts in the tray.
    visible: false
    title: appController.appName

    property int page: 0
    property bool _quitting: false
    readonly property bool _trayHide: prefsController.closeToTray && appController.trayAvailable

    titleActions: [
        AppButton {
            kind: "ghost"
            compact: true
            iconName: "settings"
            toolTipText: "Preferences (Ctrl+,)"
            onClicked: mainWin.openPreferences()
        },
        AppButton {
            kind: "ghost"
            compact: true
            iconName: "info"
            toolTipText: "About " + appController.appName + " (F1)"
            onClicked: aboutDialog.open()
        }
    ]

    function openPreferences() {
        preferences.show()
        preferences.raise()
        preferences.requestActivate()
    }

    onClosing: function (close) {
        if (mainWin._quitting) return
        if (mainWin._trayHide) {
            close.accepted = false
            mainWin.hide()
        } else if (queueController.runningCount > 0) {
            close.accepted = false
            quitDialog.open()
        } else {
            Qt.quit()
        }
    }

    Connections {
        target: appController
        function onNotice(message) { toast.show(message) }
        function onClipboardLink(url) { clipboardOffer.offer(url) }
    }
    Connections {
        target: updateController
        function onNotice(message) { if (!preferences.visible && !aboutDialog.visible) toast.show(message) }
    }
    Connections {
        target: queueController
        function onWhenDoneCountdown(action) { countdown.start(action) }
    }

    Shortcut { sequence: "Ctrl+,"; onActivated: mainWin.openPreferences() }
    Shortcut { sequence: "F1"; onActivated: aboutDialog.open() }
    Shortcut { sequence: "Ctrl+1"; onActivated: mainWin.page = 0 }
    Shortcut { sequence: "Ctrl+2"; onActivated: mainWin.page = 1 }
    Shortcut { sequence: "Ctrl+3"; onActivated: mainWin.page = 2 }
    Shortcut { sequence: "Ctrl+4"; onActivated: mainWin.page = 3 }
    Shortcut { sequence: "Ctrl+L"; onActivated: { mainWin.page = 0; downloads.focusLink() } }
    Shortcut { sequence: "Ctrl+Shift+O"; onActivated: { mainWin.page = 0; downloads.showOptions() } }
    Shortcut {
        sequence: "Ctrl+Shift+P"
        onActivated: queueController.paused ? queueController.resumeAll() : queueController.pauseAll()
    }
    // Ctrl+V outside a text box pastes the link into the link box.
    Shortcut {
        sequences: [StandardKey.Paste]
        enabled: !(mainWin.activeFocusItem instanceof TextInput) && !(mainWin.activeFocusItem instanceof TextEdit)
        onActivated: { mainWin.page = 0; downloads.pasteLink() }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            color: Theme.surface

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: Theme.spaceLg
                anchors.rightMargin: Theme.spaceLg
                spacing: Theme.spaceSm

                Repeater {
                    model: [
                        { "text": "Downloads", "icon": "download", "tip": "Downloads (Ctrl+1)" },
                        { "text": "Library", "icon": "library", "tip": "Finished downloads (Ctrl+2)" },
                        { "text": "Subscriptions", "icon": "bell", "tip": "Channels and playlists watched for new uploads (Ctrl+3)" },
                        { "text": "Sign-ins", "icon": "key", "tip": "Sites you signed in to (Ctrl+4)" }
                    ]
                    delegate: AppButton {
                        required property var modelData
                        required property int index
                        kind: mainWin.page === index ? "primary" : "ghost"
                        text: modelData.text
                        iconName: modelData.icon
                        toolTipText: modelData.tip
                        onClicked: mainWin.page = index
                    }
                }
                Item { Layout.fillWidth: true }
            }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Theme.border }
        }

        // The expanded audio player takes the page area; the pages keep their state behind it.
        NowPlaying {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: audioBar.expanded && playerController.hasAudio
            player: audioBar.player
            title: audioBar.title
            artist: audioBar.artist
        }

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !(audioBar.expanded && playerController.hasAudio)
            currentIndex: mainWin.page

            DownloadsPage {
                id: downloads
                onOpenPreferences: { mainWin.openPreferences(); preferences.showTools() }
                onOpenSignIns: mainWin.page = 3
            }
            LibraryPage {}
            SubscriptionsPage {}
            SignInsPage {
                onOpenLink: function (url) { mainWin.page = 0; downloads.openLink(url) }
            }
        }

        AudioBar {
            id: audioBar
            Layout.fillWidth: true
            Layout.preferredHeight: implicitHeight
        }

        RunBar {
            id: runBar
            Layout.fillWidth: true
            updates: updateController
        }
    }

    // Links (from a browser's address bar or a page) and .txt link lists dropped on the window.
    DropArea {
        id: drop
        anchors.fill: parent
        keys: ["text/uri-list", "text/plain"]
        onDropped: function (event) {
            var text = ""
            if (event.hasUrls) {
                for (var i = 0; i < event.urls.length; ++i) {
                    var url = event.urls[i].toString()
                    if (url.startsWith("file:") && url.toLowerCase().endsWith(".txt")) text += appController.readTextFile(url) + "\n"
                    else if (url.startsWith("http")) text += url + "\n"
                }
            }
            if (text.trim().length === 0 && event.hasText) text = event.text
            if (text.trim().length > 0) {
                mainWin.page = 0
                downloads.addDropped(text.trim())
                event.acceptProposedAction()
            }
        }
        Rectangle {
            anchors.fill: parent
            visible: drop.containsDrag
            color: Theme.dropFill
            border.width: 2
            border.color: Theme.accent
            Text {
                anchors.centerIn: parent
                text: "Drop links to download them"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontTitle
                font.weight: Font.DemiBold
                color: Theme.text
            }
        }
    }

    Toast {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: runBar.height + audioBar.height + Theme.spaceLg
    }

    // A copied link the app can download (Preferences: Offer copied links).
    Popup {
        id: clipboardOffer
        property string url: ""
        function offer(url) {
            clipboardOffer.url = url
            clipboardOffer.open()
            offerTimer.restart()
        }
        x: (mainWin.width - width) / 2
        y: mainWin.height - runBar.height - audioBar.height - height - Theme.spaceXl * 3
        width: Math.min(mainWin.width - 2 * Theme.spaceXl, 560)
        padding: Theme.spaceMd
        closePolicy: Popup.CloseOnEscape
        background: Rectangle { radius: Theme.radiusLarge; color: Theme.surface; border.width: 1; border.color: Theme.borderStrong }
        Timer { id: offerTimer; interval: 12000; onTriggered: clipboardOffer.close() }
        contentItem: RowLayout {
            spacing: Theme.spaceSm
            Icon { name: "link"; size: Theme.iconLg; color: Theme.accent }
            Text {
                Layout.fillWidth: true
                text: "Download the copied link?\n" + clipboardOffer.url
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                color: Theme.text
                elide: Text.ElideMiddle
                maximumLineCount: 2
            }
            AppButton {
                kind: "primary"
                text: "Download"
                iconName: "download"
                onClicked: {
                    queueController.addLinks(clipboardOffer.url, prefsController.value("downloads.preset"))
                    clipboardOffer.close()
                }
            }
            AppButton {
                kind: "ghost"
                compact: true
                iconName: "close"
                toolTipText: "Not this one"
                onClicked: clipboardOffer.close()
            }
        }
    }

    // The queue finished with an action chosen: a minute to change one's mind.
    AppDialog {
        id: countdown
        property string action: "nothing"
        property int left: 60
        function start(action) {
            countdown.action = action
            countdown.left = 60
            countdown.open()
            countdownTimer.start()
        }
        title: "Downloads finished"
        standardButtons: Dialog.Cancel
        defaultButton: Dialog.Cancel
        width: 420
        onRejected: { countdownTimer.stop(); queueController.cancelWhenDone() }
        Timer {
            id: countdownTimer
            interval: 1000
            repeat: true
            onTriggered: {
                countdown.left -= 1
                if (countdown.left <= 0) {
                    countdownTimer.stop()
                    countdown.close()
                    queueController.performWhenDone()
                }
            }
        }
        Text {
            width: parent.width
            text: ({"quit": "The app quits", "sleep": "The PC goes to sleep", "hibernate": "The PC hibernates",
                    "shutdown": "The PC shuts down"})[countdown.action] + " in " + countdown.left + " seconds."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.text
            wrapMode: Text.WordWrap
        }
    }

    AppDialog {
        id: quitDialog
        title: "Quit while downloading?"
        standardButtons: Dialog.Yes | Dialog.Cancel
        defaultButton: Dialog.Cancel
        width: 420
        onAccepted: { mainWin._quitting = true; Qt.quit() }
        Text {
            width: parent.width
            text: "Downloads stop now and continue from where they stopped the next time the app opens."
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.text
            wrapMode: Text.WordWrap
        }
    }

    AppDialog {
        id: aboutDialog
        title: "About " + appController.appName
        standardButtons: Dialog.Close
        defaultButton: Dialog.Close
        width: Math.min(mainWin.width - 2 * Theme.spaceXl, 480)

        ColumnLayout {
            width: parent.width
            spacing: Theme.spaceMd

            Text {
                Layout.fillWidth: true
                text: appController.appName + " " + appController.appVersion
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSubtitle
                font.weight: Font.DemiBold
                color: Theme.text
            }
            Text {
                Layout.fillWidth: true
                text: appController.appDescription + "."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                color: Theme.textMuted
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                text: "Downloads are made by yt-dlp, with FFmpeg and Deno; they are separate free programs under "
                    + "their own licenses. Download only videos you own or have permission to save."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
                wrapMode: Text.WordWrap
            }
            RowLayout {
                spacing: Theme.spaceSm
                AppButton {
                    text: "Check for updates"
                    iconName: "sync"
                    enabled: updateController.status !== "checking" && updateController.status !== "downloading"
                    onClicked: updateController.checkNow()
                }
                AppButton {
                    kind: "ghost"
                    text: "Releases"
                    iconName: "openExternal"
                    onClicked: updateController.openDownloadPage()
                }
            }
            Text {
                Layout.fillWidth: true
                visible: text !== ""
                text: updateController.message
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: updateController.status === "error" ? Theme.danger : Theme.textMuted
                wrapMode: Text.WordWrap
            }
            Text {
                Layout.fillWidth: true
                text: "Free and open source (MIT). Built by " + appController.appAuthor + "."
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
                wrapMode: Text.WordWrap
            }
        }
    }

    PreferencesWindow {
        id: preferences
        transientParent: mainWin
    }

    PlayerWindow {
        id: videoPlayer
        transientParent: null  // a window of its own: it can sit on another screen or stay on top
    }
}
