pragma Singleton
import QtQuick

// Design tokens shared by every window, following the same structure as gfgLock, CC-Gen-Ultimate,
// and gfgShield so the apps feel like one family; gfgRoyal Media Downloader carries a rose accent.
// Colors keep at least a 4.5:1 contrast ratio for body and muted text against their surfaces in
// both themes (WCAG 2.1 AA).
QtObject {
    id: theme

    // Bound by every AppWindow to appController.currentTheme.
    property bool dark: false
    // Bound by every AppWindow to appController.animations: false while Windows' Animation effects
    // setting is off, which makes every duration below 0.
    property bool motion: true

    // ── Motion ───────────────────────────────────────────────────────────────
    // Short, so a control answers at once and only eases into its new look.
    readonly property int motionFast:   motion ? 120 : 0  // hover, press, and checked colors
    readonly property int motionMedium: motion ? 180 : 0  // fades: dialogs, toasts, check marks
    readonly property int motionSlow:   motion ? 260 : 0  // Smart Mode's bulb lighting up

    // ── Surfaces ─────────────────────────────────────────────────────────────
    readonly property color background:   dark ? "#15171c" : "#f3f4f6"
    readonly property color surface:      dark ? "#1d2027" : "#ffffff"
    readonly property color surfaceAlt:   dark ? "#242832" : "#f7f8fa"
    readonly property color surfaceHover: dark ? "#2b303b" : "#eceff3"
    readonly property color titleBar:     dark ? "#111317" : "#e9ebef"
    readonly property color border:       dark ? "#343a46" : "#d6dae1"
    readonly property color borderStrong: dark ? "#4a5263" : "#b7bec9"
    // Outlines of text boxes, combo boxes, and switch tracks: at least 3:1 against surface and
    // surfaceHover (WCAG 1.4.11), where border is kept light for card edges and dividers.
    readonly property color inputBorder:  dark ? "#7a8394" : "#7d8694"

    // ── Text ─────────────────────────────────────────────────────────────────
    readonly property color text:      dark ? "#e8eaee" : "#1a1d23"
    readonly property color textMuted: dark ? "#a6adba" : "#565f6c"
    readonly property color textOnAccent: "#ffffff"

    // ── Accent and status (gfgRoyal Media Downloader rose) ───────────────────
    readonly property color accent:      dark ? "#fb7185" : "#be123c"
    readonly property color accentFill:  dark ? "#c81e4a" : "#be123c"
    readonly property color accentHover: dark ? "#a8173d" : "#9f1239"
    readonly property color accentSoft:  dark ? "#3b1620" : "#ffe4e6"
    readonly property color success:     dark ? "#4ac26b" : "#17733a"
    readonly property color successSoft: dark ? "#16301f" : "#e3f4e8"
    readonly property color danger:      dark ? "#ff6b63" : "#c62828"
    readonly property color dangerSoft:  dark ? "#3a1d1d" : "#fdecec"
    readonly property color warning:     dark ? "#e0b341" : "#8a5a00"
    readonly property color warningSoft: dark ? "#332a16" : "#fbf2dd"
    readonly property color focusRing:   dark ? "#fda4af" : "#be123c"
    // Smart Mode's lit bulb: a golden glass, with its edge, base, and rays in a deeper gold that
    // stands out from the warm tint (warningSoft) behind it.
    readonly property color bulbLit:     dark ? "#ffcc33" : "#f5b800"
    readonly property color bulbEdge:    dark ? "#ffe08a" : "#8a5a00"
    // The overlay shown while links or files are dragged over the window.
    readonly property color dropFill:    dark ? "#33c81e4a" : "#1abe123c"
    // Dims the window behind a dialog. Dark in both themes: a pale wash over the dark theme looks
    // like Windows fading out a frozen app.
    readonly property color scrim:       dark ? "#8c000000" : "#4d000000"
    // A media thumbnail's kind badge sits on a picture, so it is dark in both themes.
    readonly property color mediaBadge:     "#d914161b"
    readonly property color mediaBadgeText: "#ffffff"
    // The video player's text and controls sit on the picture under a dark shade, so they are
    // light in both themes; the hover, checked, and pressed fills are white washes over the video.
    readonly property color overlayText:    "#ffffff"
    readonly property color overlayAccent:  "#fda4af"
    readonly property color overlayHover:   "#26ffffff"
    readonly property color overlayChecked: "#33ffffff"
    readonly property color overlayPressed: "#40ffffff"
    // Toasts use the opposite theme's colors so they stand out from the window.
    // Tooltips (GfgmdStyle/ToolTip.qml): a raised card in the window's own theme, as Windows 11 draws them.
    readonly property color toolTip:       dark ? "#2b303b" : "#ffffff"
    readonly property color toolTipBorder: dark ? "#4a5263" : "#c3c9d2"
    readonly property color toolTipShadow: dark ? "#59000000" : "#1f000000"
    readonly property color inverseSurface: dark ? "#e8eaee" : "#22262e"
    readonly property color inverseText:    dark ? "#1a1d23" : "#ffffff"
    // The title bar's close button turns Windows red on hover in both themes.
    readonly property color closeHover:     "#c42b1c"
    readonly property color closeHoverText: "#ffffff"

    // ── Typography (pixel sizes) ─────────────────────────────────────────────
    readonly property string fontFamily: "Segoe UI Variable Text"
    readonly property int fontCaption: 12
    readonly property int fontBody: 13
    readonly property int fontSubtitle: 15
    readonly property int fontTitle: 18

    // ── Spacing and shape ────────────────────────────────────────────────────
    readonly property int spaceXs: 4
    readonly property int spaceSm: 8
    readonly property int spaceMd: 12
    readonly property int spaceLg: 16
    readonly property int spaceXl: 24
    readonly property int radius: 6
    readonly property int radiusLarge: 10
    readonly property int controlHeight: 34

    // ── Icon sizes (pixel sizes) ─────────────────────────────────────────────
    readonly property int iconXs: 10
    readonly property int iconSm: 12
    readonly property int iconMd: 14
    readonly property int iconLg: 16
    readonly property int iconXl: 28

    // A tooltip shown because a control took keyboard focus closes after this many ms, so it
    // can't cover the window while focus stays put. Hover tooltips stay until the pointer leaves.
    readonly property int focusTipTimeout: 5000

    // ── Icons (Segoe Fluent Icons on Windows 11, MDL2 Assets on Windows 10) ──
    readonly property string iconFont: Qt.fontFamilies().indexOf("Segoe Fluent Icons") >= 0
        ? "Segoe Fluent Icons" : "Segoe MDL2 Assets"
    readonly property var icons: ({
        add: "\uE710",
        remove: "\uE738",
        delete: "\uE74D",
        clear: "\uE894",
        cancel: "\uE711",
        close: "\uE8BB",
        minimize: "\uE921",
        maximize: "\uE922",
        restore: "\uE923",
        settings: "\uE713",
        info: "\uE946",
        completed: "\uE930",
        checkMark: "\uE73E",
        check: "\uE73E",
        error: "\uEA39",
        warning: "\uE7BA",
        refresh: "\uE72C",
        sync: "\uE895",
        download: "\uE896",
        chevronDown: "\uE70D",
        chevronUp: "\uE70E",
        chevronRight: "\uE76C",
        openExternal: "\uE8A7",
        more: "\uE712",
        globe: "\uE774",
        video: "\uE714",
        audio: "\uE8D6",
        play: "\uE768",
        pause: "\uE769",
        stop: "\uE71A",
        folder: "\uE8B7",
        folderOpen: "\uE838",
        link: "\uE71B",
        paste: "\uE77F",
        copy: "\uE8C8",
        library: "\uE8F1",
        history: "\uE81C",
        account: "\uE77B",
        key: "\uE8D7",
        lock: "\uE72E",
        search: "\uE721",
        filter: "\uE71C",
        calendar: "\uE787",
        clock: "\uE823",
        bell: "\uEA8F",
        live: "\uE7C8",
        subtitles: "\uE7F0",
        repair: "\uE90F",
        speed: "\uEC4A",
        power: "\uE7E8",
        moon: "\uE708",
        up: "\uE74A",
        downArrow: "\uE74B",
        skip: "\uE893",
        import: "\uE8B5",
        list: "\uEA37",
        fullscreen: "\uE740",
        exitFullscreen: "\uE73F",
        volume: "\uE767",
        mute: "\uE74F",
        shuffle: "\uE8B1",
        repeatAll: "\uE8EE",
        repeatOne: "\uE8ED",
        previous: "\uE892",
        next: "\uE893",
        rewind: "\uEB9E",
        forward: "\uEB9D",
        lyrics: "\uE8E4",
        pin: "\uE718",
        unpin: "\uE77A"
    })
}
