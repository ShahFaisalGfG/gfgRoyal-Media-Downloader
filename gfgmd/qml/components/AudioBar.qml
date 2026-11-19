// qmllint disable unqualified
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtMultimedia

// The audio player along the bottom of the main window: cover, title and artist, previous, play,
// next, shuffle and repeat, the position, volume, and speed. "Lyrics and queue" expands it into the
// Now playing view (synced lyrics and the play order). Media keys work while the app has focus.
// Playback resumes where a song stopped last time, unless it was near the start or the end.
Rectangle {
    id: bar

    property alias player: audio
    property bool expanded: false
    readonly property bool playing: audio.playbackState === MediaPlayer.PlayingState
    // The song's own tags first (audio downloads tag the clean title and artist), else the library's.
    readonly property string title: audio.metaData.stringValue(MediaMetaData.Title) || playerController.audioTitle
    readonly property string artist: audio.metaData.stringValue(MediaMetaData.ContributingArtist)
        || audio.metaData.stringValue(MediaMetaData.AlbumArtist) || playerController.audioArtist
    property string _path: ""
    property real _pendingSeek: 0

    function toggle() { bar.playing ? audio.pause() : audio.play() }
    function seekTo(ms) { audio.position = Math.max(0, Math.min(audio.duration, ms)) }
    function savePosition() {
        if (bar._path.length > 0 && audio.duration > 0)
            playerController.savePosition(bar._path, audio.position, audio.duration)
    }
    function load() {
        bar.savePosition()
        bar._path = playerController.audioPath
        bar._pendingSeek = playerController.resumeAt(bar._path)
        audio.source = playerController.audioUrl
        audio.play()
    }
    // Previous restarts the song when it has played a few seconds, like most players.
    function previous() {
        if (audio.position > 4000 || playerController.audioIndex === 0) bar.seekTo(0)
        else playerController.stepAudio(-1)
    }

    visible: playerController.hasAudio
    implicitHeight: visible ? 76 : 0
    color: Theme.surface

    Connections {
        target: playerController
        // A new song was loaded by onAudioChanged; asking for the same song again plays it.
        function onAudioRequested() {
            if (playerController.audioPath !== bar._path) bar.load()
            else if (!bar.playing) audio.play()
        }
        function onAudioChanged() {
            if (playerController.audioPath !== bar._path) {
                if (playerController.hasAudio) bar.load()
                else { bar.savePosition(); audio.stop(); bar._path = ""; bar.expanded = false }
            }
        }
        function onTogglePlayRequested() { if (playerController.hasAudio) bar.toggle() }
    }

    MediaPlayer {
        id: audio
        audioOutput: AudioOutput {
            volume: playerController.volume
            muted: playerController.muted
        }
        playbackRate: playerController.speed
        onPlaybackStateChanged: playerController.setAudioPlaying(bar.playing)
        onMediaStatusChanged: {
            if ((audio.mediaStatus === MediaPlayer.LoadedMedia || audio.mediaStatus === MediaPlayer.BufferedMedia)
                    && bar._pendingSeek > 0 && audio.seekable) {
                audio.position = bar._pendingSeek
                bar._pendingSeek = 0
            }
            if (audio.mediaStatus === MediaPlayer.EndOfMedia) {
                playerController.savePosition(bar._path, audio.duration, audio.duration)
                // The same file again (repeat one, or a one-song list on repeat) starts over here;
                // another song is loaded by onAudioChanged.
                if (playerController.audioEnded() && playerController.audioPath === bar._path) {
                    audio.position = 0
                    audio.play()
                }
            }
        }
        onErrorOccurred: function (error, errorString) {
            appController.notice.emit("This song can't be played here: " + (errorString || "unknown error"))
        }
    }

    Timer { interval: 5000; repeat: true; running: bar.playing; onTriggered: bar.savePosition() }

    Shortcut { sequences: ["Media Play", "Toggle Media Play/Pause"]; enabled: bar.visible; onActivated: bar.toggle() }
    Shortcut { sequence: "Media Pause"; enabled: bar.visible; onActivated: audio.pause() }
    Shortcut { sequence: "Media Next"; enabled: bar.visible; onActivated: playerController.stepAudio(1) }
    Shortcut { sequence: "Media Previous"; enabled: bar.visible; onActivated: bar.previous() }
    Shortcut { sequence: "Media Stop"; enabled: bar.visible; onActivated: audio.stop() }

    Rectangle { anchors.top: parent.top; width: parent.width; height: 1; color: Theme.border }

    RowLayout {
        anchors.fill: parent
        anchors.leftMargin: Theme.spaceLg
        anchors.rightMargin: Theme.spaceLg
        spacing: Theme.spaceMd

        Cover {
            Layout.preferredWidth: 52
            Layout.preferredHeight: 52
        }

        ColumnLayout {
            Layout.preferredWidth: 200
            Layout.maximumWidth: 260
            Layout.fillWidth: true
            spacing: 2
            Text {
                Layout.fillWidth: true
                text: bar.title
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontBody
                font.weight: Font.DemiBold
                color: Theme.text
            }
            Text {
                Layout.fillWidth: true
                visible: text.length > 0
                text: bar.artist
                elide: Text.ElideRight
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontCaption
                color: Theme.textMuted
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: 0
            RowLayout {
                Layout.alignment: Qt.AlignHCenter
                spacing: Theme.spaceXs
                AppButton {
                    kind: "ghost"; compact: true; iconName: "shuffle"
                    toolTipText: playerController.shuffle ? "Shuffle is on" : "Shuffle"
                    checkable: true
                    checked: playerController.shuffle
                    onClicked: playerController.setShuffle(!playerController.shuffle)
                }
                AppButton { kind: "ghost"; compact: true; iconName: "previous"; toolTipText: "Previous song"; onClicked: bar.previous() }
                AppButton {
                    kind: "primary"; compact: true
                    iconName: bar.playing ? "pause" : "play"
                    toolTipText: bar.playing ? "Pause" : "Play"
                    onClicked: bar.toggle()
                }
                AppButton {
                    kind: "ghost"; compact: true; iconName: "next"; toolTipText: "Next song"
                    enabled: playerController.audioIndex + 1 < playerController.audioCount || playerController.repeat === "all"
                    onClicked: playerController.stepAudio(1)
                }
                AppButton {
                    kind: "ghost"; compact: true
                    iconName: playerController.repeat === "one" ? "repeatOne" : "repeatAll"
                    checkable: true
                    checked: playerController.repeat !== "off"
                    toolTipText: playerController.repeat === "one" ? "Repeating this song"
                        : playerController.repeat === "all" ? "Repeating the list" : "Repeat"
                    onClicked: playerController.cycleRepeat()
                }
            }
            SeekBar {
                Layout.fillWidth: true
                position: audio.position
                duration: audio.duration
                seekable: audio.seekable
                onSeek: function (ms) { bar.seekTo(ms) }
            }
        }

        AppButton {
            kind: "ghost"; compact: true
            iconName: playerController.muted || playerController.volume === 0 ? "mute" : "volume"
            toolTipText: playerController.muted ? "Unmute" : "Mute"
            onClicked: playerController.setMuted(!playerController.muted)
        }
        Slider {
            Layout.preferredWidth: 90
            from: 0
            to: 1
            value: playerController.muted ? 0 : playerController.volume
            focusPolicy: Qt.TabFocus
            Accessible.name: "Volume"
            onMoved: {
                playerController.setVolume(value)
                if (playerController.muted && value > 0) playerController.setMuted(false)
            }
        }
        AppButton {
            id: speedButton
            kind: "ghost"; compact: true
            text: playerController.speed + "×"
            toolTipText: "Playback speed"
            onClicked: speedMenu.openAbove(speedButton)
        }
        AppButton {
            kind: "ghost"; compact: true
            iconName: bar.expanded ? "chevronDown" : "lyrics"
            toolTipText: bar.expanded ? "Back to the app" : "Lyrics and queue"
            onClicked: bar.expanded = !bar.expanded
        }
        AppButton {
            kind: "ghost"; compact: true; iconName: "close"; toolTipText: "Stop and close the player"
            onClicked: { bar.savePosition(); playerController.stopAudio() }
        }
    }

    ChoiceMenu {
        id: speedMenu
        title: "Speed"
        choices: playerController.speeds.map(function (speed) { return speed === 1 ? "Normal" : speed + "×" })
        current: playerController.speeds.indexOf(playerController.speed)
        onChosen: function (index) { playerController.setSpeed(playerController.speeds[index]) }
    }

    // The song's cover: from its tags or beside it, else its online thumbnail, else a music icon.
    component Cover: Rectangle {
        radius: Theme.radius
        color: Theme.surfaceAlt
        border.width: 1
        border.color: Theme.border
        clip: true
        Icon { anchors.centerIn: parent; name: "audio"; size: Theme.iconLg; color: Theme.textMuted; visible: art.status !== Image.Ready }
        Image {
            id: art
            anchors.fill: parent
            anchors.margins: 1
            source: playerController.audioCover.length > 0 ? playerController.audioCover
                : playerController.audioThumbnail.length > 0 ? thumbnails.localFor(playerController.audioThumbnail, thumbnails.revision) : ""
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            sourceSize.width: 160
            Accessible.ignored: true
        }
    }
}
