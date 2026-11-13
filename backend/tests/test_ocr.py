import io
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

from app.errors import ApiError
from app.ingestion import JPEG, PDF, PNG, WEBP, extract, validate_file
from app.ocr import UNCLEAR, _BINDING_WORKER, ocr_image, parse_tsv


def settings(**changes):
    return SimpleNamespace(
        **(
            {
                "ocr_enabled": True,
                "ocr_languages": "vie+eng",
                "tesseract_path": "tesseract",
                "ocr_timeout": 10,
                "ocr_data_dir": None,
                "ocr_min_confidence": 60,
                "max_image_pixels": 24_000_000,
                "ocr_max_pages": 20,
                "max_pages": 300,
                "libreoffice_path": "soffice",
            }
            | changes
        )
    )


def tsv(words):
    rows = ["level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"]
    for number, (word, confidence, line, paragraph) in enumerate(words, 1):
        rows.append(f"5\t1\t1\t{paragraph}\t{line}\t{number}\t1\t1\t10\t10\t{confidence}\t{word}")
    return "\n".join(rows)


SAMPLE_TSV = tsv([("Noi", 95, 1, 1), ("dung", 96, 1, 1), ("minh", 96, 2, 1), ("hoa.", 95, 2, 1)])


@pytest.mark.parametrize("format,mime,suffix", [("PNG", PNG, ".png"), ("JPEG", JPEG, ".jpg"), ("WEBP", WEBP, ".webp")])
def test_image_formats_validate(tmp_path, format, mime, suffix):
    path = tmp_path / ("photo" + suffix)
    Image.new("RGB", (120, 80), "white").save(path, format=format)
    validate_file(path, mime)


def test_mime_mismatch_and_corrupt_image_rejected(tmp_path):
    path = tmp_path / "photo.jpg"
    Image.new("RGB", (120, 80), "white").save(path, format="PNG")
    with pytest.raises(ApiError) as caught:
        validate_file(path, JPEG)
    assert caught.value.code == "INVALID_IMAGE"
    path.write_bytes(b"not an image")
    with pytest.raises(ApiError):
        validate_file(path, PNG)


def test_image_pixel_limit_and_animation(tmp_path):
    path = tmp_path / "photo.png"
    image = Image.new("RGB", (100, 100), "white")
    image.save(path)
    with pytest.raises(ApiError) as caught:
        validate_file(path, PNG, settings(max_image_pixels=9000))
    assert caught.value.code == "IMAGE_TOO_LARGE"
    image.save(path, save_all=True, append_images=[Image.new("RGB", (100, 100), "black")], duration=100, loop=0)
    with pytest.raises(ApiError) as caught:
        validate_file(path, PNG)
    assert caught.value.code == "INVALID_IMAGE"


def test_tsv_keeps_lines_and_paragraphs():
    text, warnings = parse_tsv(
        tsv(
            [
                ("Dong", 95, 1, 1),
                ("mot", 95, 1, 1),
                ("Dong", 90, 2, 1),
                ("hai", 90, 2, 1),
                ("Doan", 95, 1, 2),
                ("moi", 95, 1, 2),
            ]
        )
    )
    assert text == "Dong mot\nDong hai\n\nDoan moi"
    assert len(warnings) == 1


def test_uncertain_numbers_are_masked_not_reconstructed():
    text, warnings = parse_tsv(tsv([("Thuoc", 96, 1, 1), ("500mg", 12, 1, 1), ("x2", 42, 1, 1), ("vien", 98, 1, 1)]))
    assert text == f"Thuoc {UNCLEAR} vien"
    assert "500mg" not in text and "x2" not in text
    assert "2/4" in warnings[-1]


@pytest.mark.parametrize(
    "value,code",
    [
        ("not tsv", "OCR_BAD_RESPONSE"),
        (tsv([]), "OCR_NO_TEXT"),
        (tsv([("impossible", 2, 1, 1)]), "OCR_UNREADABLE"),
    ],
)
def test_no_text_or_bad_tsv_never_succeeds(value, code):
    with pytest.raises(ApiError) as caught:
        parse_tsv(value)
    assert caught.value.code == code


def test_cli_is_local_and_timeout_bounded(monkeypatch):
    calls = []
    monkeypatch.setattr("app.ocr.shutil.which", lambda _: "tesseract")

    def run(args, **kwargs):
        calls.append((args, kwargs))
        assert kwargs["timeout"] == 10 and "shell" not in kwargs
        output = "List of available languages (2):\nvie\neng\n" if "--list-langs" in args else SAMPLE_TSV
        return SimpleNamespace(returncode=0, stdout=output.encode(), stderr=b"")

    monkeypatch.setattr("app.ocr.subprocess.run", run)
    text, _ = ocr_image(Image.new("RGB", (200, 100), "white"), settings())
    assert text == "Noi dung\nminh hoa."
    assert "-l" in calls[-1][0] and calls[-1][0][-1] == "tsv"
    temporary_image = Path(calls[-1][0][1])
    assert not temporary_image.exists()


def test_binding_fallback_uses_killable_childprocess(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ocr.shutil.which", lambda _: None)
    monkeypatch.setattr("app.ocr.importlib.util.find_spec", lambda _: object())
    for language in ("vie", "eng"):
        (tmp_path / f"{language}.traineddata").write_bytes(b"fixture")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0, stdout=SAMPLE_TSV.encode(), stderr=b"")

    monkeypatch.setattr("app.ocr.subprocess.run", run)
    text, _ = ocr_image(Image.new("RGB", (200, 100), "white"), settings(ocr_data_dir=str(tmp_path)))
    assert text and calls[0][1] == "-c" and "tesserocr" in calls[0][2]
    assert str(tmp_path) in calls[0]


def test_missing_engine_and_languages(monkeypatch):
    monkeypatch.setattr("app.ocr.shutil.which", lambda _: None)
    monkeypatch.setattr("app.ocr.importlib.util.find_spec", lambda _: None)
    image = Image.new("RGB", (200, 100), "white")
    with pytest.raises(ApiError) as caught:
        ocr_image(image, settings())
    assert caught.value.code == "OCR_UNAVAILABLE"
    monkeypatch.setattr("app.ocr.shutil.which", lambda _: "tesseract")
    monkeypatch.setattr("app.ocr.subprocess.run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout=b"eng\n"))
    with pytest.raises(ApiError) as caught:
        ocr_image(image, settings())
    assert caught.value.code == "OCR_LANGUAGE_MISSING"


def test_ocr_timeout_and_stderr_are_sanitized(monkeypatch):
    monkeypatch.setattr("app.ocr.shutil.which", lambda _: "tesseract")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("secret-file-name", 10)

    monkeypatch.setattr("app.ocr.subprocess.run", timeout)
    with pytest.raises(ApiError) as caught:
        ocr_image(Image.new("RGB", (200, 100), "white"), settings())
    assert caught.value.code == "OCR_TIMEOUT" and "secret" not in caught.value.message
    monkeypatch.setattr(
        "app.ocr.subprocess.run",
        lambda *a, **kw: SimpleNamespace(returncode=1, stdout=b"", stderr=b"private prescription"),
    )
    with pytest.raises(ApiError) as caught:
        ocr_image(Image.new("RGB", (200, 100), "white"), settings())
    assert caught.value.code == "OCR_FAILED" and "private prescription" not in caught.value.message


def test_image_extract_canonical_pdf_and_metadata(tmp_path, monkeypatch):
    image = Image.new("RGB", (200, 100), "white")
    image.save(tmp_path / "original.jpg", format="JPEG")
    monkeypatch.setattr("app.ingestion.ocr_image", lambda image, settings: ("Hồ sơ minh họa.", ["Đối chiếu ảnh gốc."]))
    assert extract(tmp_path, JPEG, settings()) == ["Hồ sơ minh họa."]
    assert len(PdfReader(tmp_path / "source.pdf").pages) == 1
    metadata = json.loads((tmp_path / "extraction.json").read_text(encoding="utf-8"))
    assert metadata["method"] == "ocr" and metadata["ocr_pages"] == [1]
    assert metadata["engine"] == "tesseract-local"


def text_pdf(path):
    document = canvas.Canvas(str(path))
    document.drawString(30, 800, "Text document")
    document.showPage()
    document.save()


def test_existing_text_pdf_does_not_use_ocr(tmp_path, monkeypatch):
    text_pdf(tmp_path / "original.pdf")

    def fail(*args):
        raise AssertionError("Text PDF should not OCR")

    monkeypatch.setattr("app.ingestion.ocr_image", fail)
    assert "Text document" in extract(tmp_path, PDF, settings())[0]
    assert json.loads((tmp_path / "extraction.json").read_text())["method"] == "text"


def test_scanned_pdf_ocr_uses_original_page_numbers(tmp_path, monkeypatch):
    pytest.importorskip("pypdfium2")
    Image.new("RGB", (400, 300), "white").save(tmp_path / "original.pdf", format="PDF")
    monkeypatch.setattr("app.ingestion.ocr_image", lambda image, settings: ("Văn bản OCR.", ["OCR minh họa."]))
    assert extract(tmp_path, PDF, settings()) == ["Văn bản OCR."]
    metadata = json.loads((tmp_path / "extraction.json").read_text(encoding="utf-8"))
    assert metadata["method"] == "ocr" and metadata["ocr_pages"] == [1]


def test_mixed_pdf_preserves_text_page_and_ocr_page(tmp_path, monkeypatch):
    pytest.importorskip("pypdfium2")
    text_pdf(tmp_path / "text.pdf")
    photo = io.BytesIO()
    Image.new("RGB", (400, 300), "white").save(photo, format="PDF")
    writer = PdfWriter()
    writer.add_page(PdfReader(tmp_path / "text.pdf").pages[0])
    writer.add_page(PdfReader(io.BytesIO(photo.getvalue())).pages[0])
    writer.write(tmp_path / "original.pdf")
    monkeypatch.setattr("app.ingestion.ocr_image", lambda image, settings: ("Ảnh ở trang hai.", ["OCR minh họa."]))
    pages = extract(tmp_path, PDF, settings())
    assert "Text document" in pages[0] and pages[1] == "Ảnh ở trang hai."
    metadata = json.loads((tmp_path / "extraction.json").read_text(encoding="utf-8"))
    assert metadata["method"] == "mixed" and metadata["ocr_pages"] == [2]


def test_ocr_page_limit_fails_before_render(tmp_path, monkeypatch):
    Image.new("RGB", (400, 300), "white").save(tmp_path / "original.pdf", format="PDF")
    with pytest.raises(ApiError) as caught:
        extract(tmp_path, PDF, settings(ocr_max_pages=0))
    assert caught.value.code == "OCR_PAGE_LIMIT_EXCEEDED"


@pytest.mark.parametrize("has_header", [True, False])
def test_binding_worker_handles_tesserocr_tsv_without_header(tmp_path, monkeypatch, has_header):
    path = tmp_path / "input.png"
    Image.new("RGB", (100, 100), "white").save(path)

    class FakeAPI:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def SetImage(self, image):
            pass

        def Recognize(self):
            pass

        def GetTSVText(self, level):
            assert level == 0
            return SAMPLE_TSV if has_header else SAMPLE_TSV.split("\n", 1)[1]

    output = io.BytesIO()
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, "tesserocr", SimpleNamespace(PyTessBaseAPI=lambda **kw: FakeAPI()))
        patch.setattr(sys, "argv", ["binding-worker", str(path), str(tmp_path), "vie+eng", "6"])
        patch.setattr(sys, "stdout", SimpleNamespace(buffer=output))
        exec(_BINDING_WORKER, {})
    value = output.getvalue().decode()
    assert value.count("level\tpage_num") == 1
    assert parse_tsv(value)[0] == "Noi dung\nminh hoa."


def test_nonfinite_confidence_is_not_trusted():
    with pytest.raises(ApiError) as caught:
        parse_tsv(tsv([("uncertain", float("nan"), 1, 1)]))
    assert caught.value.code == "OCR_BAD_RESPONSE"


def searchable_scan(path, text, *, invisible=True):
    document = canvas.Canvas(str(path))
    image = Image.new("RGB", (400, 600), "white")
    document.drawImage(ImageReader(image), 0, 0, width=595, height=842)
    layer = document.beginText(30, 800)
    layer.setTextRenderMode(3 if invisible else 0)
    layer.textLine(text)
    document.drawText(layer)
    document.showPage()
    document.save()


LEGACY_OCR = " ".join(["Vi6n thu6c li6u d6ng c6n nh6n"] * 15)
RECOGNIZED = "Nội dung được đọc lại từ ảnh gốc. " * 25


def test_corrupt_nonempty_searchable_scan_is_reocrred(tmp_path, monkeypatch):
    pytest.importorskip("pypdfium2")
    searchable_scan(tmp_path / "original.pdf", LEGACY_OCR)
    assert PdfReader(tmp_path / "original.pdf").pages[0].extract_text().strip()
    monkeypatch.setattr("app.ingestion.ocr_image", lambda image, settings: (RECOGNIZED, []))
    assert extract(tmp_path, PDF, settings()) == [RECOGNIZED]
    metadata = json.loads((tmp_path / "extraction.json").read_text(encoding="utf-8"))
    assert metadata["ocr_pages"] == [1] and metadata["repaired_text_pages"] == [1]
    assert metadata["pipeline_version"] and metadata["warnings"]


@pytest.mark.parametrize(
    "text,invisible",
    [
        ("English searchable document. The storage region has 3 zones and 12 services. " * 20, True),
        ("B2B H2O ISO9001 A100 x86 500mg 15mg/kg technical specifications and test results. " * 20, True),
        (LEGACY_OCR, False),
    ],
)
def test_clean_searchable_and_visible_digital_text_not_reocrred(tmp_path, monkeypatch, text, invisible):
    searchable_scan(tmp_path / "original.pdf", text, invisible=invisible)

    def fail(*args):
        raise AssertionError("Useful/digital text should not trigger automatic OCR")

    monkeypatch.setattr("app.ingestion.ocr_image", fail)
    assert text in extract(tmp_path, PDF, settings())[0]
    metadata = json.loads((tmp_path / "extraction.json").read_text())
    assert metadata["method"] == "text" and metadata["repaired_text_pages"] == []


@pytest.mark.parametrize("recognized", ["Too short", "[không rõ] " * 100, LEGACY_OCR])
def test_failed_repair_never_indexes_original_garbled_layer(tmp_path, monkeypatch, recognized):
    pytest.importorskip("pypdfium2")
    searchable_scan(tmp_path / "original.pdf", LEGACY_OCR)
    monkeypatch.setattr("app.ingestion.ocr_image", lambda image, settings: (recognized, []))
    with pytest.raises(ApiError) as caught:
        extract(tmp_path, PDF, settings())
    assert caught.value.code == "OCR_UNREADABLE"
    assert not (tmp_path / "extraction.json").exists()
