"""Local Tesseract OCR. No image or OCR text is sent to an external service."""

from __future__ import annotations

import csv
import io
import importlib.util
import math
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from .errors import ApiError


OCR_NOTICE = "Nội dung được đọc bằng OCR; hãy đối chiếu ảnh gốc, nhất là tên thuốc, liều lượng và cách dùng."
UNCLEAR = "[không rõ]"

# A child process, not a background thread, lets subprocess.run enforce a hard
# timeout even while Tesseract's C API is busy. Parameters are argv, never code.
_BINDING_WORKER = """
import sys
from PIL import Image
import tesserocr
path, data, languages, psm = sys.argv[1:]
with Image.open(path) as image:
    with tesserocr.PyTessBaseAPI(path=data, lang=languages, psm=int(psm)) as api:
        api.SetImage(image)
        api.Recognize()
        output = api.GetTSVText(0)
        if not output.startswith('level\\t'):
            output = 'level\\tpage_num\\tblock_num\\tpar_num\\tline_num\\tword_num\\tleft\\ttop\\twidth\\theight\\tconf\\ttext\\n' + output
        sys.stdout.buffer.write(output.encode('utf-8'))
"""


def _languages(settings):
    value = getattr(settings, "ocr_languages", "vie+eng")
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*", value):
        raise ApiError(503, "OCR_CONFIGURATION_INVALID", "Cấu hình ngôn ngữ OCR không hợp lệ.")
    return value


def _run(args, settings):
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            timeout=getattr(settings, "ocr_timeout", 60),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise ApiError(504, "OCR_TIMEOUT", "OCR quá thời gian xử lý. Hãy thử ảnh rõ hơn hoặc nhỏ hơn.", True) from exc
    except OSError as exc:
        raise ApiError(503, "OCR_UNAVAILABLE", "Không khởi chạy được Tesseract OCR.", True) from exc
    if result.returncode:
        # Engine stderr may include storage paths or recognized private text.
        raise ApiError(503, "OCR_FAILED", "Tesseract không xử lý được ảnh. Kiểm tra engine và dữ liệu ngôn ngữ.", True)
    return result.stdout.decode("utf-8", errors="replace") if isinstance(result.stdout, bytes) else result.stdout


def prepare_image(image: Image.Image) -> Image.Image:
    """Conservative preprocessing; do not threshold away decimal points/digits."""
    gray = ImageOps.grayscale(ImageOps.exif_transpose(image))
    gray = ImageOps.autocontrast(gray)
    longest = max(gray.size)
    scale = min(2.0, 2000 / longest) if longest < 2000 else min(1.0, 4000 / longest)
    if scale != 1:
        gray = gray.resize(
            (max(1, round(gray.width * scale)), max(1, round(gray.height * scale))), Image.Resampling.LANCZOS
        )
    return gray


def parse_tsv(tsv: str, min_confidence: float = 60) -> tuple[str, list[str]]:
    """Keep Tesseract line/paragraph order; replace uncertain words, never guess."""
    lines = []
    tokens = []
    previous_line = previous_paragraph = None
    total = uncertain = confident = 0
    try:
        reader = csv.DictReader(io.StringIO(tsv), delimiter="\t", quoting=csv.QUOTE_NONE)
        required = {"level", "block_num", "par_num", "line_num", "word_num", "conf", "text"}
        if not reader.fieldnames or not required <= set(reader.fieldnames):
            raise ValueError("Missing TSV columns")
        for row in reader:
            if row["level"] != "5" or not (row.get("text") or "").strip():
                continue
            word = re.sub(r"[\x00-\x1f\x7f]", "", row["text"]).strip()
            if not word:
                continue
            confidence = float(row["conf"])
            if not math.isfinite(confidence) or not -1 <= confidence <= 100:
                raise ValueError("Invalid word confidence")
            line = (row.get("page_num", "1"), row["block_num"], row["par_num"], row["line_num"])
            paragraph = line[:3]
            if previous_line is not None and line != previous_line:
                lines.append(" ".join(tokens))
                tokens = []
                if paragraph != previous_paragraph:
                    lines.append("")
            total += 1
            if confidence < min_confidence:
                uncertain += 1
                if not tokens or tokens[-1] != UNCLEAR:
                    tokens.append(UNCLEAR)
            else:
                confident += 1
                tokens.append(word)
            previous_line, previous_paragraph = line, paragraph
        if tokens:
            lines.append(" ".join(tokens))
    except (ValueError, TypeError, KeyError) as exc:
        raise ApiError(503, "OCR_BAD_RESPONSE", "Engine OCR trả dữ liệu không hợp lệ.") from exc
    if not total:
        raise ApiError(422, "OCR_NO_TEXT", "Không đọc được chữ trong ảnh. Hãy chụp rõ, đủ sáng và thẳng trang.")
    if not confident:
        raise ApiError(
            422, "OCR_UNREADABLE", "Chữ trong ảnh quá khó đọc để trích xuất đáng tin cậy. Hãy chụp lại rõ hơn."
        )
    warnings = [OCR_NOTICE]
    if uncertain:
        warnings.append(
            f"OCR đã che {uncertain}/{total} từ có tín hiệu nhận dạng thấp bằng {UNCLEAR}; không suy đoán phần bị che."
        )
    return "\n".join(lines).strip(), warnings


def ocr_image(image: Image.Image, settings) -> tuple[str, list[str]]:
    if not getattr(settings, "ocr_enabled", True):
        raise ApiError(422, "OCR_DISABLED", "OCR đang tắt. Bật OCR để đọc ảnh hoặc PDF scan.")
    executable = shutil.which(getattr(settings, "tesseract_path", "tesseract"))
    binding = executable is None and importlib.util.find_spec("tesserocr") is not None
    if executable is None and not binding:
        raise ApiError(503, "OCR_UNAVAILABLE", "Cần cài Tesseract OCR và dữ liệu vie/eng để đọc ảnh.", True)
    languages = _languages(settings)
    data_dir = getattr(settings, "ocr_data_dir", None)
    options = ["--tessdata-dir", str(data_dir)] if data_dir else []
    if binding:
        if not data_dir:
            raise ApiError(503, "OCR_LANGUAGE_MISSING", "Cần cấu hình OCR_DATA_DIR chứa vie/eng.traineddata.")
        available = [file.stem for file in Path(data_dir).glob("*.traineddata")]
    else:
        available = _run([executable, "--list-langs", *options], settings).splitlines()
    missing = set(languages.split("+")) - {line.strip() for line in available}
    if missing:
        raise ApiError(
            503,
            "OCR_LANGUAGE_MISSING",
            "Tesseract thiếu dữ liệu ngôn ngữ OCR đã cấu hình: " + ", ".join(sorted(missing)),
        )
    psm = int(getattr(settings, "ocr_psm", 6))
    if not 0 <= psm <= 13:
        raise ApiError(503, "OCR_CONFIGURATION_INVALID", "Cấu hình phân đoạn trang OCR không hợp lệ.")
    with tempfile.TemporaryDirectory(prefix="rag-ocr-") as temporary:
        path = Path(temporary) / "input.png"
        prepared = prepare_image(image)
        try:
            prepared.save(path, format="PNG")
            if binding:
                tsv = _run(
                    [sys.executable, "-c", _BINDING_WORKER, str(path), str(data_dir), languages, str(psm)], settings
                )
            else:
                tsv = _run(
                    [executable, str(path), "stdout", "-l", languages, "--psm", str(psm), *options, "tsv"], settings
                )
        finally:
            prepared.close()
    return parse_tsv(tsv, getattr(settings, "ocr_min_confidence", 60))
