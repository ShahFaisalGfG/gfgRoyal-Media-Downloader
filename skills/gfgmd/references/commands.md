# gfgmd command reference

```text
gfgmd URL [options]
gfgmd skill {install,uninstall,path,show} [options]
```

`URL` is a link to a video, Short, playlist, channel, profile, or post on YouTube or any other site yt-dlp supports. A link typed without `https://` gets it added.

## General

| Option | Default | What it does |
|---|---|---|
| `--json` | | One JSON object per line on stdout (see json-events.md) |
| `-r`, `--resolution HEIGHT` | `1080` | Highest resolution on the shorter side; `0` for the best |
| `--output-dir FOLDER` | `Videos\gfgRoyal Media Downloader`, or `Music\gfgRoyal Media Downloader` with `--audio` | Where to save (made if it doesn't exist) |
| `--max-attempts N` | `0` | Attempts before giving up on temporary failures; `0` keeps trying |
| `--retry-delay SECONDS` | `10` | First wait between attempts; it doubles up to five minutes |
| `-c`, `--concurrent-fragments N` | `8` | Parts of a video downloaded at once, 1 to 16 |
| `--cookies FILE` | | A `cookies.txt` sign-in file exported from a browser |
| `--cookies-from-browser BROWSER[:PROFILE]` | | Read the sign-in from a browser, such as `firefox` |
| `-v`, `--verbose` | | Also report the download tools' warnings and their own error text |
| `--version` | | Print the version |

## Format

| Option | Default | What it does |
|---|---|---|
| `--audio [FORMAT]` | `mp3` when given alone | Audio only: `mp3`, `m4a`, `opus`, `vorbis`, `flac`, `wav`, or `best` (the site's own audio, unconverted) |
| `--audio-quality KBPS` | `320` | For MP3, M4A, Opus, and OGG: 320, 256, 192, 160, 128, 96, or 64 |
| `--cover square\|original` | `square` | Shape of the cover put in audio files |
| `--no-cover` | | No cover in audio files |
| `--no-lyrics` | | No synced lyrics (`.lrc`) with audio downloads |
| `--no-online-lyrics` | | Lyrics only from the site's captions, never from LRCLIB |
| `--audio-langs LANGS` | | Keep these dubbed audio tracks next to the original, such as `es,pt-BR` (MP4 or MKV) |
| `--container mp4\|mkv\|webm` | `mp4` | Video file type |
| `--codec compatible\|balanced\|best` | `balanced` | `compatible` plays everywhere; `best` allows AV1 and VP9 |
| `--subs LANGS` | | Subtitles in these languages, such as `en.*,ur` |
| `--auto-subs` | | Include automatic captions |
| `--embed-subs` | | Put the subtitles inside the video instead of separate files |
| `--keep-subs` | | Put them inside the video and keep the separate files too |
| `--sub-format srt\|vtt` | `srt` | File type of separate subtitle files |
| `--embed` | | Put the thumbnail, details, and chapters inside the video |
| `--sponsorblock mark\|remove` | | Mark or cut the sponsor parts SponsorBlock lists (YouTube) |
| `--filename-style STYLE` | `title-quality` | `title-quality`, `title`, `date-title`, or `index-title` |

## Network

| Option | What it does |
|---|---|
| `--limit-rate RATE` | Speed limit, such as `500K` or `2M` |
| `--proxy URL` | Proxy address, such as `http://proxy:8080` |
| `--force-ipv4` | Connect over IPv4 only |

## Selection

| Option | What it does |
|---|---|
| `--whole-playlist` | For a link to a video inside a playlist (`watch?v=...&list=...`), download the whole playlist; without it only that video downloads |
| `--items SPEC` | Which playlist or channel videos, by number, such as `1:5,8`; with a link to a video inside a playlist it means the playlist |
| `--live-from-start` | Record a live stream from its beginning |
| `--wait-for-video` | Wait for a scheduled stream or premiere to begin |
| `--strict` | Exit with status 1 when any video couldn't be downloaded (private, removed, ...) |

## The skill command

| Command | What it does |
|---|---|
| `gfgmd skill install` | Copy this skill into `~/.agents/skills/gfgmd` and `~/.claude/skills/gfgmd` |
| `gfgmd skill install --agent AGENT` | Into one agent's own folder (repeatable): `agents`, `amp`, `augment`, `claude`, `codex`, `continue`, `copilot`, `cursor`, `droid`, `gemini`, `goose`, `junie`, `kilo`, `kiro`, `opencode`, `openhands`, `qwen`, `roo`, `trae`, `windsurf` |
| `gfgmd skill install --dir FOLDER` | Into a skills folder of your own (the skill goes in `FOLDER\gfgmd`) |
| `gfgmd skill uninstall` | Remove it again (same `--agent` and `--dir` choices) |
| `gfgmd skill path` | List the folders it goes in and whether it is there |
| `gfgmd skill show` | Print the skill and its references |

Each takes `--json`.

## Examples

```powershell
gfgmd "https://www.youtube.com/playlist?list=PLAYLIST_ID" --json
gfgmd "https://www.youtube.com/watch?v=VIDEO_ID&list=PLAYLIST_ID" --whole-playlist --json
gfgmd "https://youtu.be/VIDEO_ID" -r 720 -c 4 --json
gfgmd "https://music.youtube.com/playlist?list=PLAYLIST_ID" --audio --json
gfgmd "https://vimeo.com/123456" --subs "en.*" --embed-subs --limit-rate 2M --json
gfgmd "https://youtu.be/VIDEO_ID" --audio-langs "es,pt-BR" --container mkv --json
gfgmd "https://www.youtube.com/watch?v=VIDEO_ID" --live-from-start --json
gfgmd "https://youtu.be/VIDEO_ID" --cookies-from-browser firefox --json
gfgmd skill install --dir "C:\Users\me\my-skills" --json
```
