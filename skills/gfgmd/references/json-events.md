# gfgmd --json events

With `--json`, stdout carries only JSON: one object per line, each with an `event` field. Read them as they come, or wait for the last line, which is always a `done` event (unless the options themselves were wrong: then argparse prints usage to stderr and the exit status is 2).

| Event | When | Fields |
|---|---|---|
| `start` | The download begins | `url`, `kind` (`video`, `audio`, or `photo` for a picture link), `output_dir` |
| `item` | A video starts | `id`, `title` |
| `progress` | At most every two seconds while downloading | `id`, `title`, `index` (the video's place in the list; 1 for a single video), `count` (how many the list holds; 0 when it isn't a list), `stage` ("Downloading", "Putting the video together", "Converting to MP3", ...), `fraction` (0 to 1, the file being fetched: captions, then the audio or video, each starting over), `overall` (0 to 1, the whole list), `downloaded` and `total` in bytes (`total` is 0 while unknown), `speed` in bytes per second, `eta` in seconds (-1 while unknown) |
| `file` | A video, song, or picture was saved | `path` (the media file; a song's `.lrc` lyrics, a video's subtitles, and a cover are beside it under the same name), `id`, `title` |
| `retry` | An attempt failed and another follows | `attempt`, `wait_seconds` |
| `error` | A video, or the download, ran into a problem | `id`, `title`, `category`, `message` (plain words, with the option that fixes it where there is one), `detail` (the download tools' own text, with `--verbose`) |
| `warning` | Something to know that didn't stop the download | `message`, `detail` (with `--verbose`) |
| `skipped` | A video that can never download (private, removed, region-locked) | `id`, `title`, `reason` |
| `result` | `gfgmd search` found a video or song | `position`, `id`, `title`, `url`, `channel`, `duration` (seconds; 0 when unknown), `views`, `thumbnail` |
| `done` | Always last | `ok`, `exit_code`, `message`, and when a download ran: `state` (`done`, `failed`, `stopped`, `needs_auth`, `disk_full`), `saved`, `skipped`, `attempts`, `output_dir`, and `category` for a failure |

`category` is one of the app's failure kinds, such as `private`, `removed`, `geo`, `auth_required`, `bot_check`, `network`, `rate_limited`, `stalled`, `disk_full`, `access_denied`, `folder_missing`, `upcoming`, `extractor_broken`, `unsupported`, `gallery_missing` (pictures need gallery-dl, which the app installs), or `unknown`.

## Example

```json
{"event": "start", "url": "https://www.youtube.com/playlist?list=PLAYLIST_ID", "kind": "audio", "output_dir": "C:\\Users\\me\\Music\\gfgRoyal Media Downloader"}
{"event": "item", "id": "aaaaaaaaaaa", "title": "First Song"}
{"event": "progress", "id": "aaaaaaaaaaa", "title": "First Song", "index": 1, "count": 2, "stage": "Downloading", "fraction": 0.42, "overall": 0.21, "downloaded": 1835008, "total": 4369066, "speed": 2097152, "eta": 1}
{"event": "file", "path": "C:\\Users\\me\\Music\\gfgRoyal Media Downloader\\My Playlist\\First Song.mp3", "id": "aaaaaaaaaaa", "title": "First Song"}
{"event": "skipped", "id": "bbbbbbbbbbb", "title": "Second Song", "reason": "This is private."}
{"event": "done", "ok": true, "exit_code": 0, "message": "Finished: 1 song saved, 1 couldn't be downloaded. The files are in C:\\Users\\me\\Music\\gfgRoyal Media Downloader", "state": "done", "saved": 1, "skipped": 1, "attempts": 1, "output_dir": "C:\\Users\\me\\Music\\gfgRoyal Media Downloader"}
```

The `skill` command's `--json` prints one object: `{"skill": "gfgmd", "installed": [paths], "failed": [{"path", "error"}]}` for install, `removed` and `not_installed` for uninstall, `folders` (`path`, `installed`) for path, and `files` (name to text) for show.
