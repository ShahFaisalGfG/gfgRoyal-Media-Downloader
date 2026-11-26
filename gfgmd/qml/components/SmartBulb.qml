import QtQuick

// Smart Mode's light bulb, drawn so it can light up: an outline bulb in the button's text color
// while off, and a golden bulb with short rays while on. Turning on, the glass fills with gold, the
// rays reach out, and the bulb pops a little; turning off, the light fades. Sized like an Icon (`size`).
Canvas {
    id: bulb

    property bool lit: false
    // The outline's color while off (the button's text color).
    property color color: Theme.text
    property real size: Theme.iconMd
    // How lit it is drawn, 0 (off) to 1 (on); eases after `lit`.
    property real glow: bulb.lit ? 1 : 0
    Behavior on glow { NumberAnimation { duration: Theme.motionSlow; easing.type: Easing.OutCubic } }

    implicitWidth: bulb.size
    implicitHeight: bulb.size
    // Decorative: the button around it carries the name and the on or off state.
    Accessible.ignored: true

    onLitChanged: if (bulb.lit && Theme.motion) pop.restart()
    onGlowChanged: bulb.requestPaint()
    onColorChanged: bulb.requestPaint()
    onWidthChanged: bulb.requestPaint()
    onHeightChanged: bulb.requestPaint()
    Connections {
        target: Theme
        function onDarkChanged() { bulb.requestPaint() }
    }

    SequentialAnimation {
        id: pop
        NumberAnimation { target: bulb; property: "scale"; to: 1.18; duration: Theme.motionFast; easing.type: Easing.OutQuad }
        NumberAnimation { target: bulb; property: "scale"; to: 1; duration: Theme.motionSlow; easing.type: Easing.OutBack }
    }

    onPaint: {
        var ctx = bulb.getContext("2d")
        ctx.reset()
        // Drawn on a 20-unit grid, scaled to the bulb's size.
        var unit = Math.min(bulb.width, bulb.height) / 20
        ctx.scale(unit, unit)
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        var g = bulb.glow
        var gold = Theme.bulbEdge
        var edge = String(Qt.tint(bulb.color, Qt.rgba(gold.r, gold.g, gold.b, g)))
        var cx = 10, cy = 8.4, r = 4.8
        // The glass: most of a circle, narrowing to the neck.
        ctx.beginPath()
        ctx.arc(cx, cy, r, Math.PI * 0.78, Math.PI * 0.22, false)
        ctx.lineTo(cx + 2.1, cy + 5.6)
        ctx.lineTo(cx - 2.1, cy + 5.6)
        ctx.closePath()
        if (g > 0) {
            ctx.globalAlpha = g
            ctx.fillStyle = String(Theme.bulbLit)
            ctx.fill()
            ctx.globalAlpha = 1
        }
        ctx.lineWidth = 1.3
        ctx.strokeStyle = edge
        ctx.stroke()
        // The base: two short bands under the neck.
        ctx.beginPath()
        ctx.moveTo(cx - 2.1, cy + 7.4)
        ctx.lineTo(cx + 2.1, cy + 7.4)
        ctx.moveTo(cx - 1.3, cy + 9.1)
        ctx.lineTo(cx + 1.3, cy + 9.1)
        ctx.stroke()
        if (g <= 0)
            return
        // Light: rays to the sides and above, clear of the glass, reaching out as it lights.
        ctx.beginPath()
        var reach = r + 1.6 + 1.6 * g
        var angles = [-150, -115, -65, -30]
        for (var i = 0; i < angles.length; ++i) {
            var a = angles[i] * Math.PI / 180
            ctx.moveTo(cx + Math.cos(a) * (r + 1.6), cy + Math.sin(a) * (r + 1.6))
            ctx.lineTo(cx + Math.cos(a) * reach, cy + Math.sin(a) * reach)
        }
        ctx.globalAlpha = g
        ctx.lineWidth = 1.2
        ctx.stroke()
    }
}
