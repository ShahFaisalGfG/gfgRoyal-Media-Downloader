// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// First run (or after a tool goes missing): get yt-dlp, FFmpeg, and Deno, with gallery-dl and spotDL,
// in one click, or use copies already on PATH. Shown above the queue until every required program is
// found. After that it offers gallery-dl and spotDL while either is missing (an update from a version
// without them, or a first-run download that failed), until Not now; downloads work without them.
Rectangle {
    id: card

    signal chooseLocations()

    // Only the extras are missing: the app is ready, so the card offers them and can be put off.
    readonly property bool extrasOnly: toolsController.ready

    implicitHeight: column.implicitHeight + 2 * Theme.spaceLg
    radius: Theme.radiusLarge
    color: Theme.accentSoft
    border.width: 1
    border.color: Theme.border

    ColumnLayout {
        id: column
        anchors.fill: parent
        anchors.margins: Theme.spaceLg
        spacing: Theme.spaceSm

        RowLayout {
            spacing: Theme.spaceSm
            Icon { name: "download"; size: Theme.iconLg; color: Theme.accent }
            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: toolsController.busy ? "Getting the download tools..."
                    : card.extrasOnly ? toolsController.extrasTitle : "Get the download tools"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSubtitle
                font.weight: Font.DemiBold
                color: Theme.text
            }
        }
        Text {
            textFormat: Text.PlainText
            Layout.fillWidth: true
            text: card.extrasOnly ? toolsController.extrasOffer
                : "The app needs a few free download tools (" + toolsController.downloadSize + "). They come "
                  + "from their official sources, are checked for safety, and stay up to date on their own."
                  + (toolsController.partlyMissing ? " Some of them are missing or damaged." : "")
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.textMuted
            wrapMode: Text.WordWrap
        }
        ProgressBar {
            Layout.fillWidth: true
            visible: toolsController.busy
            from: 0
            to: 1
            value: Math.max(0, toolsController.progress)
            indeterminate: toolsController.progress < 0
            Accessible.name: "Tool download progress"
        }
        Text {
            textFormat: Text.PlainText
            Layout.fillWidth: true
            visible: text.length > 0
            text: toolsController.stage
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontCaption
            color: Theme.textMuted
            elide: Text.ElideRight
        }
        RowLayout {
            spacing: Theme.spaceSm
            AppButton {
                visible: toolsController.canInstall && !toolsController.busy
                kind: "primary"
                text: "Download tools"
                iconName: "download"
                onClicked: toolsController.installMissing()
            }
            AppButton {
                visible: toolsController.busy
                kind: "danger"
                text: "Cancel"
                iconName: "cancel"
                onClicked: toolsController.cancel()
            }
            AppButton {
                visible: !card.extrasOnly && toolsController.foundOnPath && !toolsController.busy
                text: "Use the installed tools"
                iconName: "check"
                onClicked: prefsController.saveSettings({"tools.source": "path"})
            }
            AppButton {
                visible: !card.extrasOnly && !toolsController.busy
                kind: "ghost"
                text: "Choose locations"
                iconName: "folder"
                onClicked: card.chooseLocations()
            }
            AppButton {
                visible: card.extrasOnly && !toolsController.busy
                kind: "ghost"
                text: "Not now"
                toolTipText: "Preferences > Tools can get them later"
                onClicked: toolsController.extrasLater()
            }
        }
    }
}
