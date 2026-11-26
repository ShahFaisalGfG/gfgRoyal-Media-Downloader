"""Settings: atomic save, defaults merged in, and invalid values dropped instead of breaking the app."""

from gfgmd.utils import settings
from gfgmd.utils.settings import get_default_settings, load_settings, save_settings, take_read_error


def test_round_trip():
    current = get_default_settings()
    current["downloads"]["concurrent"] = 4
    current["formats"]["max_height"] = 720
    assert save_settings(current)
    loaded = load_settings()
    assert loaded["downloads"]["concurrent"] == 4
    assert loaded["formats"]["max_height"] == 720


def test_missing_keys_come_from_defaults():
    assert save_settings({"theme": "dark"})
    loaded = load_settings()
    assert loaded["theme"] == "dark"
    assert loaded["downloads"] == get_default_settings()["downloads"]


def test_drop_invalid_rejects_bad_values():
    defaults = get_default_settings()
    raw = {
        "theme": "purple",
        "advanced": {"log_level": "loud", "enable_logs": "yes"},
        "downloads": {"concurrent": 99, "fragments": -1, "filename_style": "weird", "keep_awake": 1,
                      "kind": "podcast", "playlist_links": "sometimes", "smart_mode": "on"},
        "formats": {"container": "avi", "sponsorblock_categories": ["sponsor", "made-up"], "max_height": 999},
        "network": {"limit_windows": [{"start": "25:00", "end": "08:00", "limit_kib": 100}], "proxy": 5},
        "schedule": {"queue_start": "2am", "when_done": "explode"},
        "tools": {"source": "internet", "channel": "beta"},
        "presets": [{"id": "built-in", "label": "x"}],
        "unknown_key": 1,
    }
    cleaned = settings.drop_invalid(raw, defaults)
    assert "theme" not in cleaned and "unknown_key" not in cleaned and "presets" not in cleaned
    assert cleaned["advanced"] == {}
    assert cleaned["downloads"] == {}
    assert cleaned["formats"] == {}
    assert cleaned["network"] == {}
    assert cleaned["schedule"] == {}
    assert cleaned["tools"] == {}


def test_drop_invalid_keeps_good_values():
    defaults = get_default_settings()
    raw = {
        "theme": "light",
        "downloads": {"concurrent": 0, "fragments": 16, "kind": "audio", "playlist_links": "video",
                      "smart_mode": False},
        "formats": {"max_height": 1080, "audio_embed_cover": False},
        "network": {"limit_windows": [{"start": "22:00", "end": "07:00", "limit_kib": 256}], "proxy": ""},
        "schedule": {"queue_start": "02:30", "when_done": "sleep"},
    }
    cleaned = settings.drop_invalid(raw, defaults)
    assert cleaned == raw


def test_the_download_buttons_preset_becomes_the_smart_mode_defaults():
    """1.0.0's presets became Smart Mode: the one the Download button used sets the Video or Audio
    defaults and the switch, so Download keeps doing what it did; the presets themselves go."""
    defaults = get_default_settings()
    built_in = {"downloads": {"preset": "video-best"}, "formats": {"container": "mp4", "codec_profile": "compatible"}}
    migrated = settings.merge_settings(defaults, settings.drop_invalid(settings.migrate(built_in), defaults))
    assert migrated["downloads"]["kind"] == "video" and "preset" not in migrated["downloads"]
    assert (migrated["formats"]["container"], migrated["formats"]["codec_profile"]) == ("mkv", "best")
    saved = {"downloads": {"preset": "user-7"},
             "presets": [{"id": "user-7", "label": "Mine", "kind": "audio", "audio_format": "opus"}]}
    migrated = settings.merge_settings(defaults, settings.drop_invalid(settings.migrate(saved), defaults))
    assert migrated["downloads"]["kind"] == "audio" and migrated["formats"]["audio_format"] == "opus"
    assert "presets" not in migrated
    gone = settings.migrate({"downloads": {"preset": "video-1080"}})
    assert gone["downloads"]["kind"] == "video" and gone["formats"]["codec_profile"] == "balanced"


def test_audio_gets_its_own_save_in_the_file_choices():
    """They start as the shared ones were; a file that already has them keeps them."""
    old = settings.migrate({"formats": {"embed_thumbnail": False, "embed_chapters": True}})
    assert old["formats"]["audio_embed_cover"] is False and old["formats"]["audio_embed_chapters"] is True
    assert "audio_embed_metadata" not in old["formats"]
    current = settings.migrate({"formats": {"embed_thumbnail": False, "audio_embed_cover": True}})
    assert current["formats"]["audio_embed_cover"] is True
    assert settings.migrate({"downloads": {"kind": "video", "preset": "audio-mp3"}})["downloads"]["kind"] == "video"


def test_damaged_file_resets_once(isolated_data):
    (isolated_data / "settings.json").write_text("{not json", encoding="utf-8")
    assert load_settings() == get_default_settings()
    assert take_read_error() is True
    assert take_read_error() is False


def test_subtitles_keep_their_placement_apart_from_whether_they_download():
    """1.0.0 kept one choice; the placement is kept on its own, for when languages are picked again."""
    assert settings.migrate({"formats": {"subtitles": "both"}})["formats"]["subtitle_placement"] == "both"
    assert "subtitle_placement" not in settings.migrate({"formats": {"subtitles": "none"}})["formats"]
    kept = settings.migrate({"formats": {"subtitles": "sidecar", "subtitle_placement": "embed"}})
    assert kept["formats"]["subtitle_placement"] == "embed"
