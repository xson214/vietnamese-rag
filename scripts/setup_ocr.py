"""Download pinned official Vietnamese/English Tesseract data, never patient images."""

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.config import Settings  # noqa: E402

REVISION = "87416418657359cb625c412a48b6e1d6d41c29bd"
CHECKSUMS = {
    "vie": "79df64caf7bcfb2a27df5042ecb6121e196eada34da774956995747636d5bfa1",
    "eng": "7d4322bd2a7749724879683fc3912cb542f19906c83bcc1a52132556427170b2",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(Settings().ocr_data_dir))
    args = parser.parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for language in ("vie", "eng"):
        url = f"https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/{REVISION}/{language}.traineddata"
        output = args.data_dir / f"{language}.traineddata"
        existing = output.read_bytes() if output.is_file() and output.stat().st_size <= 20 * 1024 * 1024 else b""
        if existing and hashlib.sha256(existing).hexdigest() == CHECKSUMS[language]:
            payload = existing
        else:
            try:
                with urllib.request.urlopen(url, timeout=60) as response:
                    payload = response.read(20 * 1024 * 1024 + 1)
            except OSError as exc:
                raise SystemExit(f"Cannot download OCR model {language}; check network and rerun setup.") from exc
        if not 10000 < len(payload) <= 20 * 1024 * 1024:
            raise SystemExit(f"Unexpected OCR model size: {language}")
        checksum = hashlib.sha256(payload).hexdigest()
        if checksum != CHECKSUMS[language]:
            raise SystemExit(f"OCR model checksum mismatch: {language}")
        if payload != existing:
            temporary = output.with_suffix(".download")
            temporary.write_bytes(payload)
            temporary.replace(output)
        records.append({"language": language, "source": url, "sha256": checksum, "bytes": len(payload)})
        print(f"{language}: {checksum} ({len(payload)} bytes)")
    (args.data_dir / "manifest.json").write_text(
        json.dumps({"revision": REVISION, "models": records}, indent=2), encoding="utf-8"
    )
    print(f"OCR models ready: {args.data_dir.resolve()}")


if __name__ == "__main__":
    main()
