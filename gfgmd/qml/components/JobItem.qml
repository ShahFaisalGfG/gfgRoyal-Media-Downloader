// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// One download in the queue: thumbnail, title, where it stands, and its buttons. Status is always
// spelled out in text with an icon, never by color alone; a failure that the user can fix offers
// its fix as a button (sign in, update the tools, choose another folder).
Rectangle {
    id: job

    signal fixRequested(int jobId, string action)
    signal menuRequested(int jobId)
    signal itemsRequested(int jobId, string title)

    required property int index
    required property int jobId
    required property string title
    required property string url
    required property string site
    required property string kind
    required property string thumbnail
    required property string jobState
    required property string statusText
    required property real progress
    required property string detail
    required property string itemText
    required property string message
    required property string action
    required property bool canPause
    required property bool canResume
    required property bool canRetry
    required property bool hasItems
    required property string lastFile
    property bool current: false

    readonly property bool _running: job.jobState === "running" || job.jobState === "retry_wait"
    readonly property color _tone: {
        switch (job.jobState) {
        case "done":       return Theme.success
        case "failed":     return Theme.danger
        case "needs_auth": return Theme.warning
        case "running":    return Theme.accent
        default:           return Theme.textMuted
        }
    }
    readonly property string _icon: {
        switch (job.jobState) {
        case "done":       return "completed"
        case "failed":     return "error"
        case "needs_auth": return "key"
        case "paused":     return "pause"
        case "cancelled":  return "cancel"
        case "scheduled":
        case "waiting_live": return "clock"
        case "running":    return "download"
        default:           return "more"
        }
    }
    readonly property string _fixText: job.action === "signin" ? "Sign in"
        : job.action === "update_tools" || job.action === "repair_tools" ? "Update tools"
        : job.action === "choose_folder" ? "Choose folder" : ""

    implicitHeight: 76
    radius: Theme.radius
    color: hover.hovered || job.current ? Theme.surfaceHover : "transparent"
    border.width: job.current && job.ListView.view && job.ListView.view.activeFocus ? 2 : 0
    border.color: Theme.focusRing

    Accessible.role: Accessible.ListItem
    Accessible.name: job.title + ", " + job.statusText + (job.detail ? ", " + job.detail : "")

    HoverHandler { id: hover }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.spaceSm
        anchors.rightMargin: Theme.spaceSm
        spacing: Theme.spaceMd

        Thumb {
            Layout.preferredWidth: 96
            Layout.preferredHeight: 54
            source: job.thumbnail
            kind: job.kind
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 3

            Text {
                Layout.fillWidth: true
                text: job.title
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                font.weight: Font.DemiBold
                color: Theme.text
                elide: Text.ElideRight
                ToolTip.visible: titleHover.hovered && truncated
                ToolTip.text: job.title
                ToolTip.delay: 700
                HoverHandler { id: titleHover }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spaceSm

                Icon {
                    name: job._icon
                    size: Theme.iconSm
                    color: job._tone
                }
                Text {
                    text: job.statusText
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontCaption
                    font.weight: Font.DemiBold
                    color: job._tone
                }
                Text {
                    Layout.fillWidth: true
                    text: [job.itemText, job.detail].filter(part => part.length > 0).join("  ·  ")
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontCaption
                    color: job.jobState === "failed" ? Theme.danger : Theme.textMuted
                    elide: Text.ElideRight
                }
            }
            ProgressBar {
                Layout.fillWidth: true
                Layout.preferredHeight: 4
                visible: job._running
                from: 0
                to: 1
                value: Math.max(0, job.progress)
                indeterminate: job.progress < 0
                Accessible.name: "Progress of " + job.title
            }
        }

        AppButton {
            visible: job._fixText.length > 0 && (job.jobState === "failed" || job.jobState === "needs_auth" || job.jobState === "paused")
            text: job._fixText
            iconName: job.action === "signin" ? "key" : job.action === "choose_folder" ? "folder" : "repair"
            toolTipText: job.message
            onClicked: job.fixRequested(job.jobId, job.action)
        }
        AppButton {
            visible: job.hasItems
            kind: "ghost"
            compact: true
            iconName: "list"
            toolTipText: "Show the videos in this download"
            onClicked: job.itemsRequested(job.jobId, job.title)
        }
        AppButton {
            visible: job.canPause
            kind: "ghost"
            compact: true
            iconName: "pause"
            toolTipText: "Pause (Space); partial files are kept and it continues from where it stopped"
            onClicked: queueController.pause(job.jobId)
        }
        AppButton {
            visible: job.canResume
            kind: "ghost"
            compact: true
            iconName: "play"
            toolTipText: "Resume (Space)"
            onClicked: queueController.resume(job.jobId)
        }
        AppButton {
            visible: job.jobState === "done" && job.lastFile.length > 0
            kind: "ghost"
            compact: true
            iconName: "play"
            toolTipText: "Play what this download saved"
            onClicked: playerController.play(job.lastFile)
        }
        AppButton {
            visible: job.canRetry && job.jobState !== "done"
            kind: "ghost"
            compact: true
            iconName: "refresh"
            toolTipText: "Try again"
            onClicked: queueController.retry(job.jobId)
        }
        AppButton {
            kind: "ghost"
            compact: true
            iconName: "more"
            toolTipText: "More actions for this download"
            onClicked: job.menuRequested(job.jobId)
        }
    }

    MouseArea {
        anchors.fill: parent
        z: -1
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onClicked: function (mouse) {
            if (job.ListView.view) job.ListView.view.currentIndex = job.index
            if (mouse.button === Qt.RightButton) job.menuRequested(job.jobId)
        }
    }
}
