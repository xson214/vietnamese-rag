import shutil
import json
import re
import threading
import subprocess
import unicodedata
import zipfile
from pathlib import Path

from pypdf import PdfReader
from PIL import Image, ImageOps, UnidentifiedImageError
from .errors import ApiError
from .ocr import UNCLEAR, ocr_image

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
JPEG = "image/jpeg"
PNG = "image/png"
WEBP = "image/webp"
IMAGE_MIMES = {JPEG, PNG, WEBP}
FILE_EXTENSIONS = {PDF: ".pdf", DOCX: ".docx", JPEG: ".jpg", PNG: ".png", WEBP: ".webp"}
MIME_BY_SUFFIX = {"pdf": PDF, "docx": DOCX, "jpg": JPEG, "jpeg": JPEG, "png": PNG, "webp": WEBP}
_FORMATS = {JPEG: "JPEG", PNG: "PNG", WEBP: "WEBP"}
_PDFIUM_LOCK = threading.Lock()
EXTRACTION_VERSION = "local-ocr-v2"


def _corruption_ratio(text):
    """Evidence of a broken OCR layer, never a spelling correction.

    Numbers embedded between lower-case letters (``thu6c``, ``Vi6n``) are
    common in old Vietnamese scan OCR. Valid numbers, units, and upper-case
    identifiers such as H2O/ISO9001 do not count toward this signal.
    """
    words = re.findall(r"[^\W_]+", text, re.UNICODE)
    broken_words = sum(
        bool(re.search(r"[^\W\d_]\d+[^\W\d_]", word)) and any(char.islower() for char in word)
        for word in words
    )
    broken_glyphs = sum(char == "\ufffd" or (unicodedata.category(char) == "Cc" and char not in "\n\r\t") for char in text)
    return broken_words, broken_words / max(1, len(words)), broken_glyphs / max(1, len(text))


def _embedded_text_needs_ocr(page, text):
    # A chart/image in a digital PDF is not enough to trigger re-OCR. Require
    # the invisible text rendering mode used by searchable scans as well as
    # repeated corruption. Clean searchable scans retain their original text.
    if not text.strip() or not page.images:
        return False
    contents = page.get_contents()
    if contents is None or not any(operator == b"Tr" and operands and operands[0] == 3 for operands, operator in contents.operations):
        return False
    broken, ratio, glyph_ratio = _corruption_ratio(text)
    return (broken >= 10 and ratio >= 0.08) or (len(text) >= 80 and glyph_ratio >= 0.02)


def _replacement_is_usable(original, replacement):
    # A failed re-OCR must never silently publish the corrupt legacy layer.
    # Confidence masks are kept verbatim; reject mostly unreadable/empty output.
    old_alpha = sum(char.isalpha() for char in original)
    readable = replacement.replace(UNCLEAR, "")
    new_alpha = sum(char.isalpha() for char in readable)
    words = re.findall(r"[^\W_]+", readable, re.UNICODE)
    masked = replacement.count(UNCLEAR)
    if new_alpha < max(40, old_alpha * 0.25) or masked / max(1, len(words) + masked) > 0.35:
        return False
    _, old_ratio, old_glyphs = _corruption_ratio(original)
    _, new_ratio, new_glyphs = _corruption_ratio(readable)
    return new_ratio < max(0.04, old_ratio * 0.5) and new_glyphs < max(0.01, old_glyphs * 0.5)


def _check_image(image, mime, settings=None):
    if image.format != _FORMATS[mime] or getattr(image, "n_frames", 1) != 1:
        raise ApiError(422, "INVALID_IMAGE", "Ảnh không khớp định dạng hoặc là ảnh động; dùng JPG, PNG hoặc WebP tĩnh.")
    limit = getattr(settings, "max_image_pixels", 24_000_000)
    if image.width < 16 or image.height < 16:
        raise ApiError(422, "INVALID_IMAGE", "Ảnh quá nhỏ để đọc tài liệu.")
    if image.width * image.height > limit:
        raise ApiError(422, "IMAGE_TOO_LARGE", "Ảnh vượt giới hạn số điểm ảnh. Hãy giảm kích thước ảnh rồi thử lại.")


def _read_image(path, mime, settings):
    try:
        with Image.open(path) as original:
            _check_image(original, mime, settings)
            oriented = ImageOps.exif_transpose(original)
            if oriented.mode in {"RGBA", "LA"} or "transparency" in oriented.info:
                rgba = oriented.convert("RGBA")
                background = Image.new("RGBA", rgba.size, "white")
                background.alpha_composite(rgba)
                result = background.convert("RGB")
                rgba.close()
                background.close()
            else:
                result = oriented.convert("RGB")
            oriented.close()
            return result
    except ApiError:
        raise
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ApiError(422, "INVALID_IMAGE", "Không đọc được ảnh hợp lệ.") from exc


def _metadata(directory, method, ocr_pages, warnings, settings, repaired_text_pages=None):
    payload = {
        "method": method,
        "ocr_pages": ocr_pages,
        "warnings": list(dict.fromkeys(warnings)),
        "engine": "tesseract-local" if ocr_pages else None,
        "languages": getattr(settings, "ocr_languages", "vie+eng") if ocr_pages else None,
        "pipeline_version": EXTRACTION_VERSION,
        "repaired_text_pages": repaired_text_pages or [],
    }
    (directory / "extraction.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _render_page(path, number, settings):
    try:
        import pypdfium2
    except ImportError as exc:
        raise ApiError(503, "OCR_RENDERER_UNAVAILABLE", "Cần cài pypdfium2 để OCR PDF scan.") from exc
    try:
        # PDFium's C API is not thread-safe, even across different documents.
        with _PDFIUM_LOCK:
            with pypdfium2.PdfDocument(str(path)) as document:
                page = document[number]
                try:
                    scale = 2.5
                    width, height = page.get_size()
                    if width * height * scale**2 > getattr(settings, "max_image_pixels", 24_000_000):
                        raise ApiError(422, "IMAGE_TOO_LARGE", "Trang PDF vượt giới hạn render OCR.")
                    bitmap = page.render(scale=scale)
                    try:
                        return bitmap.to_pil().convert("RGB")
                    finally:
                        bitmap.close()
                finally:
                    page.close()
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(422, "OCR_RENDER_FAILED", "Không render được trang PDF scan.") from exc


def validate_file(path: Path, mime: str, settings=None):
    try:
        if mime == PDF:
            if not path.read_bytes()[:1024].lstrip().startswith(b"%PDF-"):
                raise ValueError("signature")
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise ApiError(422, "INVALID_DOCUMENT", "PDF mã hóa chưa được hỗ trợ.")
            if not len(reader.pages):
                raise ValueError("empty")
        elif mime == DOCX:
            with zipfile.ZipFile(path) as archive:
                if "word/document.xml" not in archive.namelist():
                    raise ValueError("not docx")
                # Bound expansion before passing to LibreOffice.
                if sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024:
                    raise ValueError("expanded size")
        elif mime in IMAGE_MIMES:
            with Image.open(path) as image:
                _check_image(image, mime, settings)
                image.verify()
        else:
            raise ApiError(415, "UNSUPPORTED_MEDIA_TYPE", "Chỉ hỗ trợ PDF, DOCX, JPG, PNG và WebP.")
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(422, "INVALID_DOCUMENT", "File rỗng, hỏng hoặc không đúng định dạng.") from exc


def extract(directory: Path, mime: str, settings) -> list[str]:
    canonical = directory / "source.pdf"
    if mime in IMAGE_MIMES:
        with _read_image(directory / ("original" + FILE_EXTENSIONS[mime]), mime, settings) as image:
            # Viewer displays the original oriented photograph, never a guessed
            # transcription or confidence-colored synthetic replacement.
            image.save(canonical, format="PDF", resolution=150)
            text, warnings = ocr_image(image, settings)
        pages = [unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))]
        _metadata(directory, "ocr", [1], warnings, settings)
        return pages
    if mime == PDF:
        shutil.copyfile(directory / "original.pdf", canonical)
    else:
        converter = shutil.which(settings.libreoffice_path)
        if converter is None:
            raise ApiError(503, "CONVERTER_UNAVAILABLE", "Cần cài LibreOffice để chuyển DOCX sang PDF.", True)
        # A separate profile prevents collisions with a user's open Office instance.
        profile = (directory / "lo-profile").resolve().as_uri()
        try:
            result = subprocess.run(
                [
                    converter,
                    f"-env:UserInstallation={profile}",
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    str(directory),
                    str(directory / "original.docx"),
                ],
                capture_output=True,
                timeout=90,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            output = directory / "original.pdf"
            if result.returncode != 0 or not output.exists():
                raise ValueError("conversion failed")
            output.replace(canonical)
        except Exception as exc:
            raise ApiError(422, "CONVERSION_FAILED", "Không thể chuyển tài liệu DOCX sang PDF.") from exc
        finally:
            shutil.rmtree(directory / "lo-profile", ignore_errors=True)
    try:
        reader = PdfReader(canonical)
        if len(reader.pages) > settings.max_pages:
            raise ApiError(422, "PAGE_LIMIT_EXCEEDED", f"Tối đa {settings.max_pages} trang.")
        pages = [
            unicodedata.normalize("NFC", (p.extract_text() or "").replace("\r\n", "\n").replace("\r", "\n"))
            for p in reader.pages
        ]
        blank = [number for number, text in enumerate(pages) if not text.strip()]
        # A blank separator in a normal PDF is not an OCR job. Some searchable
        # scans already contain a nonempty but broken old OCR layer; inspect
        # those conservatively rather than treating any text as good text.
        repaired = [number for number, text in enumerate(pages) if _embedded_text_needs_ocr(reader.pages[number], text)]
        targets = [
            number for number in blank if not any(page.strip() for page in pages) or bool(reader.pages[number].images)
        ]
        targets = sorted(set(targets + repaired))
        if targets and not getattr(settings, "ocr_enabled", True):
            raise ApiError(422, "OCR_DISABLED", "PDF có trang scan nhưng OCR đang tắt.")
        if len(targets) > getattr(settings, "ocr_max_pages", 20):
            raise ApiError(422, "OCR_PAGE_LIMIT_EXCEEDED", "PDF vượt giới hạn số trang cần OCR trong một lần xử lý.")
        warnings, recognized_pages = [], []
        for number in targets:
            with _render_page(canonical, number, settings) as image:
                text, page_warnings = ocr_image(image, settings)
            if number in repaired:
                if not _replacement_is_usable(pages[number], text):
                    raise ApiError(
                        422,
                        "OCR_UNREADABLE",
                        f"Trang {number + 1} có lớp chữ OCR lỗi và chưa đọc lại đủ rõ. Hãy cung cấp bản scan rõ hơn.",
                    )
                warnings.append(f"Trang {number + 1}: đã đọc lại ảnh vì lớp chữ OCR cũ có dấu hiệu hỏng.")
            pages[number] = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
            recognized_pages.append(number + 1)
            warnings.extend(f"Trang {number + 1}: {warning}" for warning in page_warnings)
        if not any(page.strip() for page in pages):
            raise ApiError(422, "OCR_NO_TEXT", "Không đọc được chữ trong tài liệu.")
        method = "text" if not recognized_pages else "ocr" if len(recognized_pages) == len(pages) else "mixed"
        _metadata(directory, method, recognized_pages, warnings, settings, [number + 1 for number in repaired])
        return pages
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(422, "EXTRACTION_FAILED", "Không thể đọc nội dung PDF.") from exc
