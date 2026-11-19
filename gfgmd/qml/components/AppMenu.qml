import QtQuick
import QtQuick.Controls

// A pop-up menu in Theme colours, with AppMenuItem and AppMenuSeparator rows. Before it opens,
// it takes the width of its longest row (up to `maxWidth`), so no text is cut off, and it keeps a
// margin from the window's edges. A nested AppMenu becomes a submenu row of the same style.
Menu {
    id: menu

    property int maxWidth: 420

    function _fitWidth() {
        var widest = 0
        for (var i = 0; i < menu.count; ++i) {
            var row = menu.itemAt(i)
            if (row && row.visible) widest = Math.max(widest, row.implicitWidth)
        }
        menu.width = Math.min(Math.max(widest + menu.leftPadding + menu.rightPadding, 180), menu.maxWidth)
    }

    // Texts can change while the menu is closed (openFor() fills them in), so the width is
    // measured each time it opens.
    onAboutToShow: menu._fitWidth()

    padding: Theme.spaceXs
    margins: Theme.spaceSm
    overlap: Theme.spaceXs

    delegate: AppMenuItem {}

    background: Rectangle {
        implicitWidth: 180
        radius: Theme.radiusLarge
        color: Theme.surface
        border.width: 1
        border.color: Theme.borderStrong
    }
}
