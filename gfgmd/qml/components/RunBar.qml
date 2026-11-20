// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// The window's footer: what the queue is doing, overall progress and speed, pause or resume all,
// what to do when everything is finished, and (between downloads) the app's update notice.
Rectangle {
    id: bar

    property var updates: null

    readonly property bool _busy: queueController.runningCount > 0
    readonly property string _status: {
        var parts = []
        if (queueController.holdText.length > 0)
            parts.push("Starts at " + queueController.holdText)
        else if (queueController.paused)
            parts.push("Paused")
        if (queueController.runningCount > 0)
            parts.push(queueController.runningCount + " downloading")
        if (queueController.waitingCount > 0)
            parts.push(queueController.waitingCount + " waiting")
        if (queueController.speedText.length > 0)
            parts.push(queueController.speedText)
        if (parts.length === 0)
            return queueController.summary.length > 0 ? queueController.summary : "Ready"
        return parts.join("  ·  ")
    }

    implicitHeight: content.implicitHeight + 2 * Theme.spaceMd
    color: Theme.surface

    Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }

    RowLayout {
        id: content
        anchors.fill: parent
        anchors.leftMargin: Theme.spaceXl
        anchors.rightMargin: Theme.spaceXl
        anchors.topMargin: Theme.spaceMd
        anchors.bottomMargin: Theme.spaceMd
        spacing: Theme.spaceLg

        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spaceXs

            Text {
                Layout.fillWidth: true
                text: bar._status
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                font.weight: Font.DemiBold
                color: queueController.paused ? Theme.warning : Theme.text
                elide: Text.ElideRight
                Accessible.role: Accessible.StaticText
                Accessible.name: text
            }
            ProgressBar {
                Layout.fillWidth: true
                visible: bar._busy
                from: 0
                to: 1
                value: queueController.progress
                Accessible.name: "Overall progress"
            }
            UpdateNotice {
                Layout.fillWidth: true
                controller: bar.updates
                visible: !bar._busy && bar.updates !== null && bar.updates.bannerVisible
            }
        }

        AppButton {
            visible: queueController.holdText.length > 0
            text: "Start now"
            iconName: "play"
            toolTipText: "Start the queue now instead of at " + queueController.holdText
            onClicked: queueController.startNow()
        }

        StyledComboBox {
            Layout.preferredWidth: 170
            model: prefsController.options.whenDone
            value: queueController.whenDone
            accessibleName: "When the downloads finish"
            toolTipText: "What happens once every download is finished; a 60-second countdown lets you cancel"
            onActivated: queueController.setWhenDone(currentValue)
        }

        AppButton {
            kind: "ghost"
            text: "Open folder"
            iconName: "folderOpen"
            toolTipText: "Open " + queueController.lastFolder
            onClicked: appController.openPath(queueController.lastFolder)
        }

        AppButton {
            kind: queueController.paused ? "primary" : "secondary"
            text: queueController.paused ? "Resume all" : "Pause all"
            iconName: queueController.paused ? "play" : "pause"
            toolTipText: queueController.paused
                ? "Resume the queue and every paused download (Ctrl+Shift+P)"
                : "Pause every download; each continues from where it stopped (Ctrl+Shift+P)"
            onClicked: queueController.paused ? queueController.resumeAll() : queueController.pauseAll()
        }
    }
}
