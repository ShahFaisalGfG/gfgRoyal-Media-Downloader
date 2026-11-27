# gfgmd command reference

```text
gfgmd URL [options]
gfgmd skill {install,uninstall,path,show} [options]
```

`URL` is a link to a video, Short, playlist, channel, profile, or post on YouTube or any other site yt-dlp supports, a post or album on a picture site, a direct link to a picture, or a Spotify playlist, album, or song. A link typed without `https://` gets it added.

## General

| Option | Default | What it does |
|---|---|---|
| `--json` | | One JSON object per line on stdout (see json-events.md) |
| `-r`, `--resolution HEIGHT` | `1080` | Highest resolution on the shorter side; `0` for the best |
| `--output-dir FOLDER` | `Videos\gfgRoyal Media Downloader`, `Music\gfgRoyal Media Downloader` with `--audio`, or `Pictures\gfgRoyal Media Downloader` for pictures | Where to save (made if it doesn't exist); a post's pictures go there too |
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
| `--split-chapters` | | One file per chapter of a video that has chapters (an album becomes one song each), numbered and tagged, in a folder named after the video |
| `--no-photos` | | Save only a post's videos, not its pictures too (see Pictures) |
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
| `--section START-END` | Only this part of the video, such as `1:30-4:05`; `2:00-` runs to the end. The file name carries the times |
| `--exact-cut` | Cut `--section` at the exact times, converting the part again (slower); without it the part starts at the nearest keyframe |
| `--live-from-start` | Record a live stream from its beginning |
| `--wait-for-video` | Wait for a scheduled stream or premiere to begin |
| `--strict` | Exit with status 1 when any video couldn't be downloaded (private, removed, ...) |

## Pictures

- A post on Instagram, X, Reddit, Pinterest, TikTok, Facebook, Tumblr, or Bluesky saves its videos, then its pictures (with gallery-dl). A post with pictures only saves them. `--no-photos` keeps to the videos; `--audio` saves no pictures.
- A link to a picture site (pixiv, DeviantArt, Imgur, ArtStation, Flickr) or straight to a picture file saves pictures, whatever `--audio` asks.
- Pictures go to `Pictures\gfgRoyal Media Downloader` (or `--output-dir`). A post with one picture puts it straight in; several get a folder named after the site and the post ("Instagram DLtSAJ3t3Ia"). Pictures saved before are skipped.
- gallery-dl is one of the download tools the app installs. Without it, a post's videos still save and the command says the pictures need it.

## Spotify

- A Spotify playlist, album, or song link downloads its songs as audio (as with `--audio`, in MP3 unless `--audio` names a format): each is found on YouTube by its title, artists, and length, and saved as "Artist - Title" with Spotify's title, artists, album, track number, and cover. An album or playlist gets a folder of its own.
- `--items` picks songs by their place in the list. A song with no good match on YouTube is listed as skipped ("No matching song was found on YouTube").
- Spotify's page lists a playlist's first 100 songs; a longer one is read whole by spotDL (a download tool the app installs), which can take a few minutes. Artist and podcast links aren't supported.

## The search command

| Command | What it does |
|---|---|
| `gfgmd search WORDS` | Search YouTube and list the videos found, each with its link, channel, length, and views |
| `gfgmd search WORDS --music` | Search YouTube Music's songs instead; each link downloads with `--audio` |
| `gfgmd search WORDS --limit N` | How many results, up to 50 (default 20) |

With `--json`, each result is a `result` event (`position`, `id`, `title`, `url`, `channel`, `duration`, `views`, `thumbnail`), then `done` with `found`.

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
gfgmd "https://youtu.be/VIDEO_ID" --audio --section 1:30-4:05 --json
gfgmd "https://youtu.be/VIDEO_ID" --audio --split-chapters --json
gfgmd "https://youtu.be/VIDEO_ID" --cookies-from-browser firefox --json
gfgmd "https://www.instagram.com/p/POST_ID/" --cookies-from-browser firefox --json
gfgmd "https://x.com/USER/status/POST_ID" --no-photos --json
gfgmd "https://imgur.com/a/ALBUM_ID" --output-dir "D:\Pictures" --json
gfgmd "https://open.spotify.com/album/ALBUM_ID" --audio flac --json
gfgmd "https://open.spotify.com/playlist/PLAYLIST_ID" --items 1:10 --json
gfgmd search "lofi hip hop" --json
gfgmd search "pasoori ali sethi" --music --limit 5 --json
gfgmd skill install --dir "C:\Users\me\my-skills" --json
```
