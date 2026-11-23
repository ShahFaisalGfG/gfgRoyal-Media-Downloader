"""The Agent Skill installer: where the skill goes, replacing and removing it, and what it refuses."""

import json
import re
import sys
from pathlib import Path

import pytest

from gfgmd.utils import agent_skills

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "gfgmd"


def test_the_skill_follows_the_agent_skills_format() -> None:
    """Frontmatter with a name matching its folder (lowercase and hyphens), a description, and limits kept."""
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    front = text.split("---")[1]
    fields = dict(line.split(":", 1) for line in front.splitlines() if re.match(r"^[a-z]+:", line))
    assert agent_skills.skill_name(SKILL / "SKILL.md") == "gfgmd" == SKILL.name
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", SKILL.name) and len(SKILL.name) <= 64
    assert 0 < len(fields["description"].strip()) <= 1024
    assert len(fields["compatibility"].strip()) <= 500
    assert agent_skills.skill_files(SKILL)[0] == Path("SKILL.md")


def test_install_replace_and_remove(tmp_path: Path) -> None:
    """A copy goes in each folder, a newer one replaces it whole, and uninstall takes it out."""
    first, second = tmp_path / "one", tmp_path / "two"
    leftover = first / ".gfgmd-cut-off" / "gfgmd"
    leftover.mkdir(parents=True)  # an install stopped halfway, which an agent could load as a second copy
    for folder in (first, second):
        assert agent_skills.install(SKILL, folder) == folder / "gfgmd"
    assert (first / "gfgmd" / "references" / "commands.md").is_file()
    stale = first / "gfgmd" / "old.md"
    stale.write_text("left by an older version", encoding="utf-8")
    stale.chmod(0o444)  # read-only, as some copies leave files
    agent_skills.install(SKILL, first)
    assert not stale.exists() and not any(p.name.startswith(".gfgmd-") for p in first.iterdir())
    assert agent_skills.uninstall("gfgmd", first) is True
    assert not (first / "gfgmd").exists() and first.is_dir()
    assert agent_skills.uninstall("gfgmd", first) is False


def test_a_folder_holding_something_else_is_left_alone(tmp_path: Path) -> None:
    """A folder of the same name that isn't this skill is never replaced or removed."""
    theirs = tmp_path / "gfgmd"
    theirs.mkdir()
    (theirs / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(agent_skills.SkillError):
        agent_skills.install(SKILL, tmp_path)
    with pytest.raises(agent_skills.SkillError):
        agent_skills.uninstall("gfgmd", tmp_path)
    assert (theirs / "notes.txt").read_text(encoding="utf-8") == "mine"


@pytest.mark.skipif(sys.platform != "win32", reason="junctions are a Windows feature")
def test_a_linked_copy_is_replaced_without_touching_what_it_links_to(tmp_path: Path) -> None:
    """The `skills` installer links each agent's folder to one copy; replacing the link keeps that copy."""
    _winapi = pytest.importorskip("_winapi")
    canonical = tmp_path / "canonical"
    agent_skills.install(SKILL, canonical)
    agent_folder = tmp_path / "agent"
    agent_folder.mkdir()
    _winapi.CreateJunction(str(canonical / "gfgmd"), str(agent_folder / "gfgmd"))
    agent_skills.install(SKILL, agent_folder)
    assert not agent_skills._is_link(agent_folder / "gfgmd") and (agent_folder / "gfgmd" / "SKILL.md").is_file()
    assert (canonical / "gfgmd" / "SKILL.md").is_file()


def test_default_and_named_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without --agent the skill goes in the two shared folders; --agent and --dir add others, once each."""
    monkeypatch.setattr(agent_skills.Path, "home", lambda: tmp_path)
    assert agent_skills.target_folders() == [tmp_path / ".agents/skills", tmp_path / ".claude/skills"]
    assert agent_skills.target_folders(["cursor", "cursor"], [tmp_path / "x"]) == [
        tmp_path / ".cursor/skills", tmp_path / "x"]


def test_the_built_command_line_finds_its_bundled_skill(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """PyInstaller unpacks the skill next to the program; from source it is the repository's."""
    assert agent_skills.skill_source("gfgmd") == SKILL
    monkeypatch.setattr(agent_skills.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert agent_skills.skill_source("gfgmd") == tmp_path / "skills" / "gfgmd"
    with pytest.raises(agent_skills.SkillError, match="reinstall"):
        agent_skills.skill_files(agent_skills.skill_source("gfgmd"))


def test_commands_report_as_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """install, path, show, and uninstall each print one JSON object with --json."""
    import argparse
    parser = argparse.ArgumentParser(prog="gfgmd skill")
    agent_skills.add_skill_commands(parser, "gfgmd")

    def run(*argv: str) -> dict:
        assert agent_skills.run_skill_command(parser.parse_args(argv), "gfgmd", SKILL) == 0
        return json.loads(capsys.readouterr().out)

    assert run("install", "--dir", str(tmp_path), "--json")["installed"] == [str(tmp_path / "gfgmd")]
    assert run("path", "--dir", str(tmp_path), "--json")["folders"] == [
        {"path": str(tmp_path / "gfgmd"), "installed": True}]
    assert list(run("show", "--json")["files"])[0] == "SKILL.md"
    assert run("uninstall", "--dir", str(tmp_path), "--json") == {
        "skill": "gfgmd", "removed": [str(tmp_path / "gfgmd")], "failed": [], "not_installed": []}
