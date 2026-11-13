"""Local HTTP smoke for actual OCR; uses a synthetic, non-patient image only."""

import io
import json
import time
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    sample = ROOT / "data/samples/ocr-demo.png"
    if not sample.exists():
        raise SystemExit("Run python scripts/make_ocr_sample.py first.")
    samples = [("ocr-demo.png", sample.read_bytes(), "image/png")]
    with Image.open(sample) as image:
        output = io.BytesIO()
        image.convert("RGB").save(output, format="PDF", resolution=150)
        samples.append(("ocr-scan-demo.pdf", output.getvalue(), "application/pdf"))
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=90) as client:
        for name, content, mime in samples:
            response = client.post(
                "/api/v1/documents",
                headers={"Idempotency-Key": f"smoke-{name}-v1"},
                files={"file": (name, content, mime)},
            )
            response.raise_for_status()
            document = response.json()["document"]
            ident = document["document_id"]
            for _ in range(300):
                status = client.get(f"/api/v1/documents/{ident}/status")
                status.raise_for_status()
                state = status.json()
                if state["status"] == "ready":
                    break
                if state["status"] == "failed":
                    raise RuntimeError(state["error"])
                time.sleep(0.2)
            else:
                raise RuntimeError("OCR ingestion timeout")
            assert state["extraction"]["method"] == "ocr"
            assert state["extraction"]["ocr_pages"] == [1]
            chat = client.post(
                "/api/v1/chat",
                json={
                    "question": "Hồ sơ đăng ký được xử lý trong bao nhiêu ngày?",
                    "document_ids": [ident],
                    "generation_config": {"backend": "extractive"},
                },
            )
            chat.raise_for_status()
            answer = chat.json()
            assert answer["status"] == "answered", answer
            assert "5 ngày làm việc" in answer["answer"], answer
            assert answer["retrieval_trace"]["ocr_used"]
            citation = answer["citations"][0]
            assert citation["page_number"] == 1
            assert client.get(citation["source_url"]).content.startswith(b"%PDF")
            print(
                json.dumps(
                    {
                        "file": name,
                        "document_id": ident,
                        "method": state["extraction"]["method"],
                        "status": answer["status"],
                        "citation_page": citation["page_number"],
                        "ocr_used": True,
                    },
                    ensure_ascii=False,
                )
            )


if __name__ == "__main__":
    main()
