.pragma library

// On Windows the Menu key and Shift+F10 reach a list as a context-menu request (ContextMenu.onRequested),
// not as key presses, placed at the window's top-left corner. The row a request is for: the current
// row when it came from the keyboard, else the row under the pointer; -1 for none (the list's empty part).
function rowFor(view, position) {
    var corner = view.mapFromItem(null, 0, 0)
    if (Math.abs(position.x - corner.x) < 0.5 && Math.abs(position.y - corner.y) < 0.5)
        return view.currentIndex
    return view.indexAt(position.x + view.contentX, position.y + view.contentY)
}
