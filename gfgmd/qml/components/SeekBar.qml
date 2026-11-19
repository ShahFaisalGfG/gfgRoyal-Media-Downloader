import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

import "MediaTime.js" as MediaTime

// A player's position slider between its elapsed and total times. Dragging previews the time and
// seeks on release; hovering shows the time under the pointer. `light` draws it over video.
RowLayout {
    id: bar

    property real position: 0
    property real duration: 0
    property bool seekable: true
    property bool light: false

    signal seek(real ms)

    readonly property color _text: bar.light ? "#ffffff" : Theme.textMuted

    spacing: Theme.spaceSm

    Text {
        text: MediaTime.format(slider.pressed ? slider.value : bar.position)
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontCaption
        font.features: { "tnum": 1 }
        color: bar._text
        Accessible.ignored: true
    }

    Slider {
        id: slider
        Layout.fillWidth: true
        from: 0
        to: Math.max(1, bar.duration)
        enabled: bar.seekable && bar.duration > 0
        focusPolicy: Qt.TabFocus
        hoverEnabled: true
        Accessible.name: "Position"
        // Follow playback, except while the user drags the handle.
        Binding on value {
            when: !slider.pressed
            value: bar.position
        }
        onMoved: if (!slider.pressed) bar.seek(slider.value)
        onPressedChanged: if (!slider.pressed) bar.seek(slider.value)

        HoverHandler { id: hover }
        ToolTip {
            parent: slider
            visible: hover.hovered && bar.duration > 0
            x: Math.min(Math.max(0, hover.point.position.x - width / 2), slider.width - width)
            y: -height - 4
            text: MediaTime.format(bar.duration * Math.min(1, Math.max(0, (hover.point.position.x - slider.leftPadding)
                                                                         / Math.max(1, slider.availableWidth))))
        }
    }

    Text {
        text: MediaTime.format(bar.duration)
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontCaption
        font.features: { "tnum": 1 }
        color: bar._text
        Accessible.ignored: true
    }
}
