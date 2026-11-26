// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// "This video or the whole playlist?" for links to a video inside a playlist (watch?v=...&list=...),
// which wait in the queue controller until this answers. Download this video is the default; Esc
// and Cancel drop the links. "Don't ask again" keeps the answer (Preferences > Downloads changes it).
AppDialog {
    id: question

    // How many links wait for the answer.
    property int count: 1
    // The answer the closing button gave: "video", "playlist", or "" (Cancel, Esc).
    property string _scope: ""

    function ask(count) {
        question.count = count
        if (question.opened) return
        remember.checked = false
        question.open()
    }

    title: question.count === 1 ? "This link is a video in a playlist"
                                : question.count + " links are videos in playlists"
    standardButtons: Dialog.Yes | Dialog.No | Dialog.Cancel
    defaultButton: Dialog.Yes
    width: Math.min(parent.width - 2 * Theme.spaceXl, 520)

    function _relabel() {
        var yes = question.standardButton(Dialog.Yes)
        if (yes) yes.text = question.count === 1 ? "Download this video" : "Download these videos"
    }

    onAboutToShow: question._scope = ""
    onAccepted: question._scope = "video"
    onClosed: queueController.answerPlaylist(question._scope, question._scope !== "" && remember.checked)
    onCountChanged: question._relabel()
    Component.onCompleted: {
        question._relabel()
        question.standardButton(Dialog.No).text = "Download the whole playlist"
        question.standardButton(Dialog.No).clicked.connect(function () { question._scope = "playlist" })
    }

    ColumnLayout {
        width: parent.width
        spacing: Theme.spaceMd

        Text {
            textFormat: Text.PlainText
            Layout.fillWidth: true
            text: question.count === 1
                  ? "Download only the video you opened, or every video in its playlist?"
                  : "Download only the videos you opened, or every video in their playlists?"
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontBody
            color: Theme.text
            wrapMode: Text.WordWrap
        }
        AppCheckBox {
            id: remember
            text: "Don't ask again"
            toolTipText: "Links like this then download the way you choose now. Change it in Preferences > Downloads."
        }
    }
}
