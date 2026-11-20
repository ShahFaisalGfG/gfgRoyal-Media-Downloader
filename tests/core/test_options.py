"""Download options: a choice the app can't use is refused with advice, never with its internal value."""

import pytest

from gfgmd.core.options import DownloadOptions


@pytest.mark.parametrize(
    ("changes", "advice", "hidden"),
    [
        ({"container": "avi"}, "The file type you chose isn't available any more.", "avi"),
        ({"codec_profile": "x265"}, "The compatibility setting you chose isn't available any more.", "x265"),
        ({"audio_quality": 999}, "The audio quality you chose isn't available any more.", "999"),
        ({"subtitles": "burn"}, "The subtitle setting you chose isn't available any more.", "burn"),
        ({"fragments": 40}, "Parts at once must be from 1 to 16.", "Fragments"),
        ({"items": "first five"}, "such as 1:5,8", "items"),
        ({"subtitles": "sidecar", "subtitle_langs": "en, ur"}, "without spaces", "en, ur"),
    ],
)
def test_unusable_choices_are_explained(changes: dict[str, object], advice: str, hidden: str) -> None:
    with pytest.raises(ValueError) as error:
        DownloadOptions(**changes).validate()  # type: ignore[arg-type]
    message = str(error.value)
    assert advice in message and hidden not in message


def test_a_proxy_without_a_port_number_is_explained() -> None:
    with pytest.raises(ValueError, match="port must be a number"):
        DownloadOptions(proxy="http://proxy:abc").validate()


def test_each_video_file_type_keeps_its_own_archive() -> None:
    """MP4 keeps the original script's archive names; MKV and WebM downloads are files of their own."""
    from gfgmd.core.options import DownloadOptions
    assert DownloadOptions(max_height=0).profile == "best" and DownloadOptions(max_height=1080).profile == "1080p"
    assert DownloadOptions(container="mkv", max_height=0).profile == "best-mkv"
    assert DownloadOptions(container="webm", max_height=720).profile == "720p-webm"
    assert DownloadOptions(container="mkv").extension == "mkv"
    assert DownloadOptions(kind="audio", audio_format="vorbis").extension == "ogg"
    assert DownloadOptions(kind="audio", audio_format="best").extension == ""
