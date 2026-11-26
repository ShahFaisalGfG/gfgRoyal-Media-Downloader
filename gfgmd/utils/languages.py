# languages.py - language codes as words, and a video's subtitles as Download options lists them

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from PySide6.QtCore import QLocale

# The language part of a subtitle file's name or a caption code: "en", "en-US", "es-419", "zh-Hans", "en-orig".
_LANGUAGE_TAG = re.compile(r"^(?P<language>[A-Za-z]{2,3})(?P<rest>(?:[-_][A-Za-z0-9]+)*)$")
# YouTube's code for captions in the video's own language, made by its speech recognition.
ORIGINAL_SUFFIX = "-orig"


def language_name(code: str) -> str:
    """A language code as words: "en" -> "English", "es-419" -> "Spanish (Latin America)", "" when unknown.

    YouTube's "-orig" (captions in the video's own language, not translated) reads "(original)";
    other parts that are neither a script nor a region, such as a caption track's ID, are left out.
    """
    match = _LANGUAGE_TAG.fullmatch(code.strip())
    if match is None:
        return ""
    language = QLocale.codeToLanguage(match.group("language"))
    if language in (QLocale.Language.AnyLanguage, QLocale.Language.C):
        return ""
    details = []
    for part in re.split(r"[-_]", match.group("rest"))[1:]:
        if part.lower() == "orig":
            details.append("original")
        elif len(part) == 4 and part.isalpha():
            script = QLocale.codeToScript(part)
            if script != QLocale.Script.AnyScript:
                details.append(QLocale.scriptToString(script))
        elif (len(part) == 2 and part.isalpha()) or (len(part) == 3 and part.isdigit()):
            territory = QLocale.codeToTerritory(part)
            if territory != QLocale.Country.AnyTerritory:
                details.append(QLocale.territoryToString(territory))
    name = QLocale.languageToString(language)
    return f"{name} ({', '.join(details)})" if details else name


def subtitle_tracks(creator: Iterable[str], automatic: Iterable[str]) -> list[dict[str, Any]]:
    """A video's subtitles as Download options lists them ({code, name, kind}): the creator's own
    ("creator"), then the captions YouTube made from the video's speech ("automatic", the "-orig"
    code), then its machine translations of those ("translated"), which the list folds away.

    A translation into a language the creator wrote subtitles for is left out: those are the same
    words, better.
    """
    own = sorted(set(creator))
    tracks = [{"code": code, "name": language_name(code) or code, "kind": "creator"} for code in own]
    tracks.sort(key=lambda track: track["name"].casefold())
    spoken, translated = [], []
    for code in sorted(set(automatic) - set(own)):
        if code.endswith(ORIGINAL_SUFFIX):
            base = code[:-len(ORIGINAL_SUFFIX)]
            spoken.append({"code": code, "name": f"{language_name(base) or base} (automatic)", "kind": "automatic"})
        else:
            translated.append({"code": code, "name": language_name(code) or code, "kind": "translated"})
    translated.sort(key=lambda track: track["name"].casefold())
    return tracks + spoken + translated
