// qmllint disable unqualified
pragma ComponentBehavior: Bound
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// The expanded audio player: a large cover with the song's title and artist, its synced lyrics with
// the current line lit and kept in view (click a line to jump to it), and the play order (click a
// song to play it). Each list is one Tab stop, moved through with the arrow keys and played from
// with Enter. Lyrics come from "<song>.lrc", which audio downloads save.
Rectangle {
    id: view

    required property var player
    // The song's title and artist as the audio bar shows them (its tags first).
    required property string title
    required property string artist

    readonly property int line: playerController.lyrics.length > 0 ? playerController.lyricLine(view.player.position) : -1

    color: Theme.background

    onLineChanged: if (view.line >= 0) lyricList.positionViewAtIndex(view.line, ListView.Center)

    RowLayout {
        anchors.fill: parent
        anchors.margins: Theme.spaceXl
        spacing: Theme.spaceXl

        ColumnLayout {
            readonly property real side: Math.min(320, view.width * 0.3)
            Layout.preferredWidth: side
            Layout.maximumWidth: side
            Layout.fillHeight: true
            spacing: Theme.spaceMd

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: width
                radius: Theme.radiusLarge
                color: Theme.surfaceAlt
                border.width: 1
                border.color: Theme.border
                clip: true
                Icon { anchors.centerIn: parent; name: "audio"; size: Theme.iconXl; color: Theme.textMuted; visible: art.status !== Image.Ready }
                Image {
                    id: art
                    anchors.fill: parent
                    anchors.margins: 1
                    source: playerController.audioCover.length > 0 ? playerController.audioCover
                        : playerController.audioThumbnail.length > 0 ? thumbnails.localFor(playerController.audioThumbnail, thumbnails.revision) : ""
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    sourceSize.width: 640
                    Accessible.name: "Cover of " + view.title
                }
            }
            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                text: view.title
                wrapMode: Text.WordWrap
                maximumLineCount: 3
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontTitle
                font.weight: Font.DemiBold
                color: Theme.text
            }
            Text {
                textFormat: Text.PlainText
                Layout.fillWidth: true
                visible: text.length > 0
                text: view.artist
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSubtitle
                color: Theme.textMuted
            }
            Item { Layout.fillHeight: true }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumWidth: 220
            spacing: Theme.spaceSm

            Text {
                textFormat: Text.PlainText
                text: "Lyrics"
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSubtitle
                font.weight: Font.DemiBold
                color: Theme.text
            }
            ListView {
                id: lyricList
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: playerController.lyrics.length > 0
                clip: true
                model: playerController.lyrics
                spacing: Theme.spaceXs
                boundsBehavior: Flickable.StopAtBounds
                highlightMoveDuration: 300
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                // One Tab stop that lands on the line being sung: Up and Down move between lines,
                // and Enter or Space plays from the current one.
                activeFocusOnTab: true
                Accessible.role: Accessible.List
                Accessible.name: "Lyrics"
                onActiveFocusChanged: if (activeFocus && view.line >= 0) lyricList.currentIndex = view.line
                Keys.onPressed: function (event) {
                    if (event.key !== Qt.Key_Return && event.key !== Qt.Key_Enter && event.key !== Qt.Key_Space) return
                    if (lyricList.currentIndex >= 0) view.player.position = playerController.lyricStart(lyricList.currentIndex)
                    event.accepted = true
                }
                delegate: ItemDelegate {
                    id: lyric
                    required property string modelData
                    required property int index
                    width: lyricList.width
                    focusPolicy: Qt.NoFocus
                    Accessible.name: lyric.modelData
                    ToolTip.visible: lyric.hovered
                    ToolTip.text: "Play from this line (Enter)"
                    ToolTip.delay: 800
                    onClicked: view.player.position = playerController.lyricStart(lyric.index)
                    contentItem: Text {
                        textFormat: Text.PlainText
                        text: lyric.modelData.length > 0 ? lyric.modelData : "♪"
                        wrapMode: Text.WordWrap
                        font.family: Theme.fontFamily
                        font.pixelSize: lyric.index === view.line ? Theme.fontTitle : Theme.fontSubtitle
                        font.weight: lyric.index === view.line ? Font.Bold : Font.Normal
                        color: lyric.index === view.line ? Theme.accent : lyric.index < view.line ? Theme.textMuted : Theme.text
                        Behavior on font.pixelSize { NumberAnimation { duration: 150 } }
                    }
                    background: Item {}
                    FocusRing { anchors.fill: parent; visible: lyric.ListView.isCurrentItem && lyricList.activeFocus }
                }
            }
            EmptyState {
                Layout.fillWidth: true
                Layout.fillHeight: true
                visible: playerController.lyrics.length === 0
                iconName: "lyrics"
                title: "No lyrics for this song"
                text: "Songs get lyrics when the site has captions or an online lyrics service knows the song. "
                    + "Turn on lyrics in Preferences > Audio."
            }
        }

        // The play order; on a narrow window the lyrics need the room, and the bar's Next still works.
        ColumnLayout {
            readonly property real side: Math.min(300, view.width * 0.26)
            visible: view.width >= 980
            Layout.preferredWidth: side
            Layout.maximumWidth: side
            Layout.fillHeight: true
            spacing: Theme.spaceSm

            Text {
                textFormat: Text.PlainText
                text: "Up next  ·  " + (playerController.audioIndex + 1) + " of " + playerController.audioCount
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSubtitle
                font.weight: Font.DemiBold
                color: Theme.text
            }
            ListView {
                id: queueList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                model: playerController.queue
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                // One Tab stop that lands on the song playing: Up and Down move, Enter or Space plays.
                activeFocusOnTab: true
                Accessible.role: Accessible.List
                Accessible.name: "Up next"
                onActiveFocusChanged: if (activeFocus) queueList.currentIndex = playerController.audioIndex
                Keys.onPressed: function (event) {
                    if (event.key !== Qt.Key_Return && event.key !== Qt.Key_Enter && event.key !== Qt.Key_Space) return
                    if (queueList.currentIndex >= 0) playerController.jumpTo(queueList.currentIndex)
                    event.accepted = true
                }
                delegate: ItemDelegate {
                    id: song
                    required property int index
                    required property string title
                    required property string artist
                    required property bool current
                    width: queueList.width
                    highlighted: song.current
                    focusPolicy: Qt.NoFocus
                    Accessible.name: song.title + (song.artist ? ", " + song.artist : "")
                    onClicked: playerController.jumpTo(song.index)
                    contentItem: ColumnLayout {
                        spacing: 0
                        Text {
                            textFormat: Text.PlainText
                            Layout.fillWidth: true
                            text: song.title
                            elide: Text.ElideRight
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontBody
                            font.weight: song.current ? Font.DemiBold : Font.Normal
                            color: song.current ? Theme.accent : Theme.text
                        }
                        Text {
                            textFormat: Text.PlainText
                            Layout.fillWidth: true
                            visible: text.length > 0
                            text: song.artist
                            elide: Text.ElideRight
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontCaption
                            color: Theme.textMuted
                        }
                    }
                    FocusRing { anchors.fill: parent; visible: song.ListView.isCurrentItem && queueList.activeFocus }
                }
            }
        }
    }

    // The ring on a focused list's current row, as the Downloads and Library rows draw it.
    component FocusRing: Rectangle {
        radius: Theme.radius
        color: "transparent"
        border.width: 2
        border.color: Theme.focusRing
    }
}
