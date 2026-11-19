.pragma library

// "1:02:03" or "2:03" from milliseconds, for the players' time labels.
function format(ms) {
    var total = Math.max(0, Math.floor((ms || 0) / 1000))
    var hours = Math.floor(total / 3600)
    var minutes = Math.floor((total % 3600) / 60)
    var seconds = total % 60
    var mm = hours > 0 && minutes < 10 ? "0" + minutes : "" + minutes
    var ss = seconds < 10 ? "0" + seconds : "" + seconds
    return hours > 0 ? hours + ":" + mm + ":" + ss : mm + ":" + ss
}
