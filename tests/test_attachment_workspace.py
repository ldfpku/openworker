import base64
import hashlib
from pathlib import Path

import pytest

from coworker.attachment_workspace import materialize_pdf_attachments
from coworker.attachments import build_user_content


def _pdf_part(name: str, raw: bytes) -> dict:
    return {
        "type": "file",
        "file": {
            "filename": name,
            "file_data": "data:application/pdf;base64," + base64.b64encode(raw).decode(),
        },
    }


def test_pdf_bytes_reach_session_scratch_without_changing_original(tmp_path: Path):
    raw = b"%PDF-1.4\n1 0 obj <<>> endobj\n%%EOF\n"
    original = [_pdf_part("../form.pdf", raw), _pdf_part("notes.pdf", raw)]
    output = materialize_pdf_attachments(original, str(tmp_path))

    assert output[0] is original[0]
    assert output[2] is original[1]
    assert len(output) == 4
    paths = list((tmp_path / "attachments").glob("*.pdf"))
    assert len(paths) == 2
    assert all(path.read_bytes() == raw for path in paths)
    assert all(str(tmp_path / "attachments") in output[i]["text"] for i in (1, 3))
    assert hashlib.sha256(raw).hexdigest() in output[1]["text"]
    assert not (tmp_path / "form.pdf").exists()


def test_invalid_payload_has_no_tool_path(tmp_path: Path):
    content = [{"type": "file", "file": {"filename": "broken.pdf", "file_data": "data:application/pdf;base64,%%%"}}]
    assert materialize_pdf_attachments(content, str(tmp_path)) == content
    assert not (tmp_path / "attachments").exists()


def test_symlinked_attachment_directory_cannot_escape_session(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    scratch = tmp_path / "session"
    scratch.mkdir()
    try:
        (scratch / "attachments").symlink_to(outside, target_is_directory=True)
    except OSError as exc:  # Windows without Developer Mode / admin rights
        pytest.skip(f"cannot create a directory symlink here: {exc}")
    with pytest.raises(ValueError, match="leaves the session scratch"):
        materialize_pdf_attachments([_pdf_part("form.pdf", b"%PDF-1.4\n")], str(scratch))
    assert not list(outside.iterdir())


def test_composer_pdf_content_exposes_exact_original_bytes(tmp_path: Path):
    raw = b"%PDF-1.4\nsynthetic form\n%%EOF\n"
    data_url = "data:application/pdf;base64," + base64.b64encode(raw).decode()
    content = build_user_content("Use the form", [
        {"kind": "pdf", "name": "form.pdf", "data_url": data_url},
    ])
    output = materialize_pdf_attachments(content, str(tmp_path))
    assert output[1] is content[1]
    assert output[1]["file"]["file_data"] == data_url
    assert len(output) == 3
    path = next((tmp_path / "attachments").glob("*.pdf"))
    assert path.read_bytes() == raw
    assert str(path) in output[2]["text"]


# -- fork wiring: the chat socket hook and conversation delete -----------------


def _real_pdf_bytes() -> bytes:
    import io

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def test_ws_user_message_copies_pdf_original_into_session_scratch(tmp_path: Path):
    from fastapi.testclient import TestClient

    from coworker.providers import AssistantTurn, ModelCapabilities, ProviderClient
    from coworker.server.app import create_app
    from coworker.server.manager import SessionManager

    class Provider(ProviderClient):
        def complete(self, *, model, messages, tools=None, **settings):
            return AssistantTurn(text="ok", finish_reason="stop")

        def capabilities(self, model):
            return ModelCapabilities(pdf=True)

    manager = SessionManager(workspace=tmp_path, provider=Provider())
    manager._prefs["scratch_base"] = str(tmp_path / "scratch")
    raw = _real_pdf_bytes()
    data_url = "data:application/pdf;base64," + base64.b64encode(raw).decode()
    client = TestClient(create_app(manager))
    with client.websocket_connect("/ws/session/pdfsess") as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({
            "type": "user_message",
            "text": "fill this form",
            "attachments": [{"kind": "pdf", "name": "form.pdf", "data_url": data_url}],
        })
        for _ in range(200):
            if ws.receive_json()["type"] == "turn_done":
                break

    folder = tmp_path / "scratch" / "pdfsess" / "attachments"
    copies = list(folder.glob("*.pdf"))
    assert len(copies) == 1 and copies[0].read_bytes() == raw
    user = next(m for m in manager._engines["pdfsess"].messages if m.get("role") == "user")
    assert any(p.get("type") == "file" for p in user["content"])
    assert any(str(copies[0]) in (p.get("text") or "") for p in user["content"])

    # Deleting the conversation removes the copies, even for a project-backed session
    # whose primary folder is kept.
    assert manager.delete_session("pdfsess")["ok"]
    assert not folder.exists()
    assert tmp_path.is_dir()


def test_delete_survives_an_unremovable_attachment_folder(tmp_path: Path, monkeypatch):
    import shutil

    from coworker.server.manager import SessionManager
    from coworker.sessions import SessionRecord

    manager = SessionManager(workspace=tmp_path, provider=None)
    manager._prefs["scratch_base"] = str(tmp_path / "scratch")
    project = tmp_path / "project"
    project.mkdir()
    folder = tmp_path / "scratch" / "sess-a" / "attachments"
    folder.mkdir(parents=True)
    manager.session_store.save(
        SessionRecord(session_id="sess-a", workspace=str(project), model="m", mode="interactive")
    )

    def boom(*args, **kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(shutil, "rmtree", boom)
    assert manager.delete_session("sess-a")["ok"]
    assert project.is_dir()
