// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// First run (or after a tool goes missing): get yt-dlp, FFmpeg, and Deno with one click, or use
// copies already on PATH. Shown above the queue until every program is found.
Rectangle {
    id: card

    signal chooseLocations()

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
                Layout.fillWidth: true
                text: toolsController.busy ? "Getting the download tools..." : "Get the download tools"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSubtitle
                font.weight: Font.DemiBold
                color: Theme.text
            }
        }
        Text {
            Layout.fillWidth: true
            text: "Downloads use three free programs: yt-dlp, FFmpeg, and Deno (" + toolsController.downloadSize
                + "). They come from their official GitHub releases, are checked against their published "
                + "checksums, and stay up to date on their own."
                + (toolsController.missing.length > 0 && toolsController.missing.length < 4
                   ? " Missing now: " + toolsController.missing.join(", ") + "." : "")
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
                toolTipText: "Download yt-dlp, FFmpeg, and Deno into the app's own folder"
                onClicked: toolsController.installMissing()
            }
            AppButton {
                visible: toolsController.busy
                kind: "danger"
                text: "Cancel"
                iconName: "cancel"
                toolTipText: "Stop downloading the tools; nothing is installed until a package is complete and verified"
                onClicked: toolsController.cancel()
            }
            AppButton {
                visible: toolsController.foundOnPath && !toolsController.busy
                text: "Use the installed programs"
                iconName: "check"
                toolTipText: "Use the yt-dlp, FFmpeg, and Deno already on PATH (installed with winget, for example)"
                onClicked: prefsController.saveSettings({"tools.source": "path"})
            }
            AppButton {
                visible: !toolsController.busy
                kind: "ghost"
                text: "Choose locations"
                iconName: "folder"
                toolTipText: "Point the app at programs you installed elsewhere (Preferences > Tools)"
                onClicked: card.chooseLocations()
            }
        }
    }
}
