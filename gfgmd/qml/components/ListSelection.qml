import QtQuick

// The rows picked in a list, by id, for actions on several at once. toggle() picks or unpicks one
// and makes it the anchor; addRange() adds the rows from the anchor to another (Shift+click).
// Bindings that call contains() update as the selection changes, since they read `ids`.
QtObject {
    id: selection

    property var ids: []
    // The row index last toggled; a Shift+click range starts here.
    property int anchor: -1
    readonly property int count: selection.ids.length

    function contains(id) {
        return selection.ids.indexOf(id) >= 0
    }

    function toggle(id, index) {
        var next = selection.ids.slice()
        var at = next.indexOf(id)
        if (at >= 0) next.splice(at, 1)
        else next.push(id)
        selection.ids = next
        selection.anchor = index
    }

    function addRange(rangeIds) {
        var next = selection.ids.slice()
        for (var i = 0; i < rangeIds.length; ++i)
            if (next.indexOf(rangeIds[i]) < 0) next.push(rangeIds[i])
        selection.ids = next
    }

    function setAll(allIds) {
        selection.ids = allIds.slice()
    }

    function clear() {
        selection.ids = []
        selection.anchor = -1
    }

    // Drop the picked rows the list no longer has (a download removed elsewhere, say).
    function keep(presentIds) {
        var next = selection.ids.filter(id => presentIds.indexOf(id) >= 0)
        if (next.length !== selection.ids.length) selection.ids = next
    }
}
