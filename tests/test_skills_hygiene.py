"""The import gate — what may enter a skill folder, and what the user is told about it.

Three paths land files in the skills dir (library-pack install, a user's .zip, a user's
folder pick) and they now share one rule set (coworker/skills/hygiene.py). These tests pin
the three verdicts — content kept, build junk dropped **and reported**, credentials
refused outright — plus the ceilings that also close the old zip-bomb hole, and the
line-ending/frontmatter fidelity that a skill's own content depends on.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from coworker.skills import hygiene
from coworker.skills.store import SkillStore

MD = (
    b"---\r\nname: demo\r\ndescription: a demo\r\n"
    b"allowed-tools: read_file, grep\r\n---\r\n\r\nline one\r\nline two\r\n"
)


@pytest.fixture()
def store(tmp_path):
    s = SkillStore(global_dir=tmp_path / "global-skills")
    s._staging_dir = tmp_path / "staged"
    return s


def _zip(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, blob in entries:
            z.writestr(name, blob)
    return buf.getvalue()


def _folder(root: Path, entries: list[tuple[str, bytes]]) -> Path:
    for name, blob in entries:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(blob)
    return root


# -- classification --------------------------------------------------------------


@pytest.mark.parametrize(
    "path, verdict",
    [
        ("SKILL.md", hygiene.KEEP),
        ("scripts/run.py", hygiene.KEEP),
        ("references/guide.md", hygiene.KEEP),
        ("scripts/__pycache__/run.cpython-311.pyc", hygiene.EXCLUDE),
        ("node_modules/left-pad/index.js", hygiene.EXCLUDE),
        (".git/config", hygiene.EXCLUDE),
        (".DS_Store", hygiene.EXCLUDE),
        ("scripts/build.log", hygiene.EXCLUDE),
        (".env", hygiene.SECRET),
        (".env.production", hygiene.SECRET),
        ("keys/deploy.pem", hygiene.SECRET),
        ("id_rsa", hygiene.SECRET),
        ("credentials.json", hygiene.SECRET),
    ],
)
def test_classify(path, verdict):
    assert hygiene.classify(path)[0] == verdict


def test_classify_is_case_insensitive_and_separator_agnostic():
    assert hygiene.classify(r"scripts\__PYCACHE__\x.pyc")[0] == hygiene.EXCLUDE
    assert hygiene.classify(".ds_store")[0] == hygiene.EXCLUDE


# -- filtered, and REPORTED ------------------------------------------------------


def test_zip_drops_junk_and_reports_exactly_what_it_dropped(store):
    preview = store.stage_upload(
        _zip(
            [
                ("demo/SKILL.md", MD),
                ("demo/references/a.md", b"a"),
                ("demo/scripts/x.py", b"x"),
                ("demo/scripts/__pycache__/x.cpython-311.pyc", b"\x00" * 40),
                ("demo/scripts/__pycache__/y.cpython-311.pyc", b"\x00" * 40),
                ("demo/node_modules/left-pad/index.js", b"js"),
                ("demo/.DS_Store", b"junk"),
            ]
        ),
        "demo.zip",
    )
    assert preview["files"] == ["references/a.md", "scripts/x.py"]
    # Collapsed per excluded directory with a count (directories first, then loose
    # files), so a person can actually read it instead of scrolling 39 .pyc names.
    assert preview["skipped"] == [
        "node_modules/ (1 file)",
        "scripts/__pycache__/ (2 files)",
        ".DS_Store",
    ]


def test_folder_import_applies_the_same_gate(store, tmp_path):
    src = _folder(
        tmp_path / "src",
        [
            ("SKILL.md", MD),
            ("references/a.md", b"a"),
            ("scripts/__pycache__/x.cpython-311.pyc", b"\x00" * 40),
        ],
    )
    preview = store.stage_folder(str(src))
    assert preview["name"] == "demo"
    assert preview["files"] == ["references/a.md"]
    assert preview["skipped"] == ["scripts/__pycache__/ (1 file)"]


def test_folder_import_needs_a_skill_md(store, tmp_path):
    src = _folder(tmp_path / "notaskill", [("readme.txt", b"hi")])
    with pytest.raises(ValueError, match="no SKILL.md"):
        store.stage_folder(str(src))


# -- credentials are refused, not filtered ---------------------------------------


@pytest.mark.parametrize("secret", [".env", "scripts/deploy.pem", "id_rsa"])
def test_credentials_refuse_the_whole_import(store, secret):
    with pytest.raises(hygiene.ImportRefused) as exc:
        store.stage_upload(
            _zip([("demo/SKILL.md", MD), (f"demo/{secret}", b"hunter2")]), "demo.zip"
        )
    assert Path(secret).name in str(exc.value)  # named, so the user can go remove it
    assert not list(store._staging_dir.glob("*")) if store._staging_dir.is_dir() else True


def test_credentials_refuse_a_folder_import_too(store, tmp_path):
    src = _folder(tmp_path / "src", [("SKILL.md", MD), (".env", b"TOKEN=1")])
    with pytest.raises(hygiene.ImportRefused, match=r"\.env"):
        store.stage_folder(str(src))


# -- ceilings --------------------------------------------------------------------


def test_single_file_ceiling(store):
    blob = b"\x00" * (hygiene.LIMITS.max_file_bytes + 1)
    with pytest.raises(hygiene.ImportRefused, match="single file"):
        store.stage_upload(_zip([("demo/SKILL.md", MD), ("demo/big.bin", blob)]), "d.zip")


def test_file_count_ceiling(store):
    entries = [("demo/SKILL.md", MD)] + [
        (f"demo/f{i}.txt", b"x") for i in range(hygiene.LIMITS.max_files + 1)
    ]
    with pytest.raises(hygiene.ImportRefused, match="file limit"):
        store.stage_upload(_zip(entries), "d.zip")


def test_archive_size_ceiling(store):
    blob = b"0" * (hygiene.LIMITS.max_archive_bytes + 1024)
    with pytest.raises(hygiene.ImportRefused, match="upload limit"):
        store.stage_upload(_zip([("demo/SKILL.md", MD), ("demo/pad.txt", blob)]), "d.zip")


def test_zip_bomb_ratio_ceiling(store):
    # Compresses ~1000x; under the archive-size ceiling, so only the ratio catches it.
    blob = b"0" * (hygiene.LIMITS.max_total_bytes + 1024)
    with pytest.raises(hygiene.ImportRefused, match="expands|limit"):
        store.stage_upload(_zip([("demo/SKILL.md", MD), ("demo/x.txt", blob)]), "d.zip")


def test_depth_ceiling(store):
    deep = "demo/" + "/".join(f"d{i}" for i in range(hygiene.LIMITS.max_depth + 1)) + "/x.md"
    with pytest.raises(hygiene.ImportRefused, match="nested too deeply"):
        store.stage_upload(_zip([("demo/SKILL.md", MD), (deep, b"x")]), "d.zip")


def test_a_refused_import_leaves_nothing_staged(store):
    blob = b"\x00" * (hygiene.LIMITS.max_file_bytes + 1)
    with pytest.raises(hygiene.ImportRefused):
        store.stage_upload(_zip([("demo/SKILL.md", MD), ("demo/big.bin", blob)]), "d.zip")
    staged = list(store._staging_dir.glob("*")) if store._staging_dir.is_dir() else []
    assert staged == []


# -- fidelity: what installs is what was uploaded --------------------------------


def test_install_keeps_line_endings_and_every_frontmatter_key(store):
    preview = store.stage_upload(_zip([("demo/SKILL.md", MD)]), "demo.zip")
    saved = store.confirm_upload(preview["token"])
    out = Path(saved["path"], "SKILL.md").read_bytes()
    assert b"allowed-tools: read_file, grep" in out  # never regenerated away
    assert b"source: uploaded" in out  # provenance still stamped
    assert out.count(b"\r\n") == MD.count(b"\r\n") + 1  # +1 = the source line
    assert b"\r\r\n" not in out


def test_bare_md_upload_does_not_double_space_on_windows(store):
    """Path.write_text translates "\\n" — including the one inside an uploaded CRLF — so a
    CRLF SKILL.md used to land as CRCRLF and read back as twice as many lines."""
    preview = store.stage_upload(MD, "SKILL.md")
    saved = store.confirm_upload(preview["token"])
    out = Path(saved["path"], "SKILL.md").read_bytes()
    assert b"\r\r\n" not in out
    assert out.count(b"\r\n") == MD.count(b"\r\n") + 1


def test_library_install_shares_the_filter():
    """The library's copytree ignore is the same table, so the two paths cannot drift."""
    ignore = hygiene.copytree_ignore()
    assert ignore("/x", ["SKILL.md", "run.py", "run.pyc", ".DS_Store"]) == {
        "run.pyc",
        ".DS_Store",
    }
