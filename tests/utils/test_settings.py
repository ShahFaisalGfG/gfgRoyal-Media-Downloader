"""Settings: atomic save, defaults merged in, and invalid values dropped instead of breaking the app."""

from gfgmd.utils import settings
from gfgmd.utils.settings import get_default_settings, load_settings, save_settings, take_read_error


def test_round_trip():
    current = get_default_settings()
    current["downloads"]["concurrent"] = 4
    current["presets"] = [{"id": "user-1", "label": "Lectures", "kind": "video", "max_height": 720}]
    assert save_settings(current)
    loaded = load_settings()
    assert loaded["downloads"]["concurrent"] == 4
    assert loaded["presets"][0]["label"] == "Lectures"


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
        "downloads": {"concurrent": 99, "fragments": -1, "filename_style": "weird", "keep_awake": 1},
        "formats": {"container": "avi", "sponsorblock_categories": ["sponsor", "made-up"]},
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
        "downloads": {"concurrent": 0, "fragments": 16, "preset": "audio-mp3"},
        "network": {"limit_windows": [{"start": "22:00", "end": "07:00", "limit_kib": 256}], "proxy": ""},
        "schedule": {"queue_start": "02:30", "when_done": "sleep"},
        "presets": [{"id": "user-7", "label": "Mine", "kind": "audio", "audio_format": "opus"}],
    }
    cleaned = settings.drop_invalid(raw, defaults)
    assert cleaned == raw


def test_damaged_file_resets_once(isolated_data):
    (isolated_data / "settings.json").write_text("{not json", encoding="utf-8")
    assert load_settings() == get_default_settings()
    assert take_read_error() is True
    assert take_read_error() is False
