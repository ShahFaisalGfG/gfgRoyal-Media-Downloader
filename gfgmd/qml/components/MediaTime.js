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

// Seconds from a time typed as "90", "1:30", or "1:02:30" (the seconds may have a fraction), as the
// app's own options read it (core/options.py parse_time); -1 when it can't be read.
function parse(text) {
    var parts = String(text).trim().split(":")
    if (parts.length < 1 || parts.length > 3 || !/^\d{1,6}(\.\d{1,3})?$/.test(parts[parts.length - 1]))
        return -1
    var seconds = 0
    for (var i = 0; i < parts.length; ++i) {
        if (i < parts.length - 1 && !/^\d{1,3}$/.test(parts[i]))
            return -1
        var number = parseFloat(parts[i])
        if (i > 0 && number >= 60)
            return -1
        seconds = seconds * 60 + number
    }
    return seconds
}
