"""The installer's connection choices: read from the registry, applied once, never turning anything on."""

import sys
import uuid

import pytest

from gfgmd.config.defaults import get_default_settings
from gfgmd.utils import install_choices
from gfgmd.utils.install_choices import apply_choices, read_choices


def test_a_cleared_choice_turns_its_connection_off() -> None:
    settings = get_default_settings()
    assert apply_choices(settings, {"UpdateChecks": 1, "ToolUpdates": 1, "OnlineLyrics": 0})
    assert settings["formats"]["lyrics_online"] is False
    assert settings["updates"]["auto_check"] is True and settings["tools"]["auto_update"] is True
    assert settings["install"]["connections"] == "OnlineLyrics=0;ToolUpdates=1;UpdateChecks=1"


def test_the_installer_never_turns_a_connection_on() -> None:
    settings = get_default_settings()
    settings["updates"]["auto_check"] = False  # turned off in Preferences
    apply_choices(settings, {"UpdateChecks": 1, "ToolUpdates": 1, "OnlineLyrics": 1})
    assert settings["updates"]["auto_check"] is False


def test_an_unchanged_choice_does_not_undo_preferences() -> None:
    """A silent in-app update keeps the earlier choices: lyrics turned back on in Preferences stay on."""
    settings = get_default_settings()
    apply_choices(settings, {"UpdateChecks": 1, "ToolUpdates": 1, "OnlineLyrics": 0})
    settings["formats"]["lyrics_online"] = True
    assert not apply_choices(settings, {"UpdateChecks": 1, "ToolUpdates": 1, "OnlineLyrics": 0})
    assert settings["formats"]["lyrics_online"] is True
    # Clearing another choice on a later install turns off only that one.
    assert apply_choices(settings, {"UpdateChecks": 0, "ToolUpdates": 1, "OnlineLyrics": 0})
    assert settings["updates"]["auto_check"] is False and settings["formats"]["lyrics_online"] is True


@pytest.mark.skipif(sys.platform != "win32", reason="the installer's choices live in the Windows registry")
def test_choices_are_read_from_the_registry() -> None:
    import winreg
    key = rf"Software\gfgmd-tests-{uuid.uuid4().hex}"
    assert read_choices(key) == {}
    try:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key) as handle:
            winreg.SetValueEx(handle, "UpdateChecks", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(handle, "OnlineLyrics", 0, winreg.REG_DWORD, 0)
            winreg.SetValueEx(handle, "ToolUpdates", 0, winreg.REG_SZ, "0")  # not a 0/1 number: left out
        assert read_choices(key) == {"UpdateChecks": 1, "OnlineLyrics": 0}
    finally:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)


def test_a_source_run_leaves_settings_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only an installed copy applies them; a source checkout or a portable build has no installer."""
    monkeypatch.setattr(install_choices, "read_choices", lambda key=install_choices.CHOICES_KEY: pytest.fail("read"))
    install_choices.apply_install_choices()
