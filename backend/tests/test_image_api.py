import io
import time

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfReader

from app.config import Settings
from app.main import create_app

TEXT = "ĐƠN THUỐC MINH HỌA\nCách dùng thuốc mẫu: uống [không rõ] viên sau ăn."


def picture(format="PNG"):
    output = io.BytesIO()
    with Image.new("RGB", (220, 120), "white") as image:
        image.save(output, format=format)
    return output.getvalue()


def wait(client, ident, expected="ready"):
    for _ in range(120):
        result = client.get(f"/api/v1/documents/{ident}/status")
        if expected == "deleted" and result.status_code == 410:
            return result
        if result.status_code == 200 and result.json()["status"] == expected:
            return result
        if result.status_code == 200 and result.json()["status"] in {"failed", "delete_failed"}:
            pytest.fail(result.text)
        time.sleep(0.03)
    pytest.fail(result.text)


@pytest.mark.parametrize(
    "extension,mime,format",
    [("png", "image/png", "PNG"), ("jpg", "image/jpeg", "JPEG"), ("webp", "image/webp", "WEBP")],
)
def test_photo_upload_ocr_search_uncertain_prescription_and_delete(tmp_path, monkeypatch, extension, mime, format):
    monkeypatch.setattr("app.ingestion.ocr_image", lambda image, settings: (TEXT, ["OCR có từ không rõ."]))

    def no_external_call(*a, **kw):
        pytest.fail("Image ingestion must not use an external API")

    monkeypatch.setattr("httpx.post", no_external_call)
    app = create_app(Settings(data_dir=tmp_path))
    with TestClient(app) as client:
        result = client.post(
            "/api/v1/documents",
            headers={"Idempotency-Key": "image-one"},
            files={"file": (f"photo.{extension}", picture(format), mime)},
        )
        assert result.status_code == 202, result.text
        ident = result.json()["document"]["document_id"]
        status = wait(client, ident).json()
        assert status["extraction"]["method"] == "ocr" and status["extraction"]["ocr_pages"] == [1]
        detail = client.get(f"/api/v1/documents/{ident}").json()["document"]
        assert detail["extraction"]["warnings"]
        source = client.get(detail["source_url"])
        assert source.status_code == 200 and len(PdfReader(io.BytesIO(source.content)).pages) == 1
        search = client.post("/api/v1/search", json={"query": "thuốc mẫu cách dùng", "document_ids": [ident]}).json()
        assert search["hits"][0]["extraction"]["method"] == "ocr"
        span = search["hits"][0]["source_spans"][0]
        assert TEXT[span["start_offset"] : span["end_offset"]] == span["quote"]
        chat = client.post("/api/v1/chat", json={"question": "Theo đơn tôi uống mấy viên?", "document_ids": [ident]})
        assert chat.status_code == 200, chat.text
        assert chat.json()["status"] == "insufficient_evidence"
        assert chat.json()["retrieval_trace"]["ocr_used"] is True
        assert "không đoán" in chat.json()["answer"]
        client.delete(f"/api/v1/documents/{ident}")
        wait(client, ident, "deleted")
        assert not app.state.store.docdir(ident).exists()


def test_mime_spoof_and_pixel_limit_rejected(tmp_path):
    with TestClient(create_app(Settings(data_dir=tmp_path, max_image_pixels=1000))) as client:
        response = client.post(
            "/api/v1/documents",
            headers={"Idempotency-Key": "limit"},
            files={"file": ("photo.png", picture(), "image/png")},
        )
        assert response.status_code == 422 and response.json()["error"]["code"] == "IMAGE_TOO_LARGE"
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.post(
            "/api/v1/documents",
            headers={"Idempotency-Key": "spoof"},
            files={"file": ("photo.jpg", picture(), "image/jpeg")},
        )
        assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_IMAGE"
        response = client.post(
            "/api/v1/documents",
            headers={"Idempotency-Key": "heic"},
            files={"file": ("photo.heic", b"not supported", "image/heic")},
        )
        assert response.status_code == 415


def test_missing_ocr_engine_reports_failed_job_and_can_retry(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ocr.shutil.which", lambda *a: None)
    monkeypatch.setattr("app.ocr.importlib.util.find_spec", lambda *a: None)
    with TestClient(create_app(Settings(data_dir=tmp_path))) as client:
        response = client.post(
            "/api/v1/documents",
            headers={"Idempotency-Key": "missing"},
            files={"file": ("photo.png", picture(), "image/png")},
        )
        ident = response.json()["document"]["document_id"]
        status = wait(client, ident, "failed").json()
        assert status["error"]["code"] == "OCR_UNAVAILABLE"
        monkeypatch.setattr("app.ingestion.ocr_image", lambda *a: ("Nội dung ảnh đã đọc rõ.", []))
        assert client.post(f"/api/v1/documents/{ident}/retry", headers={"Idempotency-Key": "retry"}).status_code == 202
        assert wait(client, ident).json()["extraction"]["method"] == "ocr"
