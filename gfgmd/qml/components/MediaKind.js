.pragma library

// What to call downloaded media, in the app's own words (utils/format.py media_noun): "song" for
// audio, "picture" for photos, "video" otherwise, plural unless the count is 1.
function noun(kind, count) {
    var word = kind === "audio" ? "song" : kind === "photo" ? "picture" : "video"
    return count === undefined || count === 1 ? word : word + "s"
}

// "3 songs", "1 picture", "8 videos".
function count(number, kind) {
    return number + " " + noun(kind, number)
}
