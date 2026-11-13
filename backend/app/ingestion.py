import shutil
import subprocess
import unicodedata
import zipfile
from pathlib import Path

from pypdf import PdfReader
from .errors import ApiError

PDF = 'application/pdf'
DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'


def validate_file(path: Path, mime: str):
    try:
        if mime == PDF:
            if not path.read_bytes()[:1024].lstrip().startswith(b'%PDF-'):
                raise ValueError('signature')
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise ApiError(422, 'INVALID_DOCUMENT', 'PDF mã hóa chưa được hỗ trợ.')
            if not len(reader.pages):
                raise ValueError('empty')
        elif mime == DOCX:
            with zipfile.ZipFile(path) as archive:
                if 'word/document.xml' not in archive.namelist():
                    raise ValueError('not docx')
                # Bound expansion before passing to LibreOffice.
                if sum(i.file_size for i in archive.infolist()) > 100 * 1024 * 1024:
                    raise ValueError('expanded size')
        else:
            raise ApiError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Chỉ hỗ trợ PDF và DOCX.')
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(422, 'INVALID_DOCUMENT', 'File rỗng, hỏng hoặc không đúng định dạng.') from exc


def extract(directory: Path, mime: str, settings) -> list[str]:
    canonical = directory / 'source.pdf'
    if mime == PDF:
        shutil.copyfile(directory / 'original.pdf', canonical)
    else:
        converter = shutil.which(settings.libreoffice_path)
        if converter is None:
            raise ApiError(503, 'CONVERTER_UNAVAILABLE', 'Cần cài LibreOffice để chuyển DOCX sang PDF.', True)
        # A separate profile prevents collisions with a user's open Office instance.
        profile = (directory / 'lo-profile').resolve().as_uri()
        try:
            result = subprocess.run([
                converter, f'-env:UserInstallation={profile}', '--headless', '--convert-to',
                'pdf', '--outdir', str(directory), str(directory / 'original.docx'),
            ], capture_output=True, timeout=90, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            output = directory / 'original.pdf'
            if result.returncode != 0 or not output.exists():
                raise ValueError('conversion failed')
            output.replace(canonical)
        except Exception as exc:
            raise ApiError(422, 'CONVERSION_FAILED', 'Không thể chuyển tài liệu DOCX sang PDF.') from exc
        finally:
            shutil.rmtree(directory / 'lo-profile', ignore_errors=True)
    try:
        reader = PdfReader(canonical)
        if len(reader.pages) > settings.max_pages:
            raise ApiError(422, 'PAGE_LIMIT_EXCEEDED', f'Tối đa {settings.max_pages} trang.')
        pages = [unicodedata.normalize('NFC', (p.extract_text() or '').replace('\r\n', '\n').replace('\r', '\n')) for p in reader.pages]
        if not any(page.strip() for page in pages):
            raise ApiError(422, 'OCR_REQUIRED', 'PDF không có text. OCR chưa được hỗ trợ trong MVP.')
        return pages
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(422, 'EXTRACTION_FAILED', 'Không thể đọc nội dung PDF.') from exc
