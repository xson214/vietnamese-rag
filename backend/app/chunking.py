"""Deterministic, page-aware chunking with exact Unicode source coordinates."""

from __future__ import annotations

import hashlib
import json
import re
import uuid


def chunk_pages(document: dict, pages: list[str], strategy: str = "recursive",
                size: int = 350, overlap: int = 60) -> list[dict]:
    """Use whitespace-token budgets; encoder token limits are checked separately.

    Each chunk stays within one canonical page. This deliberately trades some
    cross-page context for simple, verifiable provenance in the first MVP.
    """
    if strategy not in {"fixed", "recursive", "heading"}:
        raise ValueError("strategy must be fixed, recursive, or heading")
    if size < 2 or not 0 <= overlap < size:
        raise ValueError("size >= 2 and 0 <= overlap < size are required")
    config = {"implementation": "page-words-v1", "strategy": strategy,
              "size": size, "overlap": overlap, "tokenizer": "unicode-whitespace-v1"}
    config_id = "chunk_" + hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()[:16]
    result = []
    for page_number, page in enumerate(pages, 1):
        tokens = list(re.finditer(r"\S+", page))
        start = 0
        while start < len(tokens):
            stop = min(start + size, len(tokens))
            if strategy != "fixed" and stop < len(tokens):
                # Prefer a natural boundary in the latter half of the window.
                minimum = start + max(overlap + 1, size // 2)
                for candidate in range(stop, minimum - 1, -1):
                    gap = page[tokens[candidate - 1].end():tokens[candidate].start()]
                    previous = tokens[candidate - 1].group()
                    heading = strategy == "heading" and "\n" in gap and (
                        tokens[candidate].group().startswith("#") or
                        re.match(r"(?:\d+[.)]|[IVX]+[.)])$", tokens[candidate].group()))
                    if "\n\n" in gap or heading or (strategy == "recursive" and previous.endswith((".", "!", "?", ";"))):
                        stop = candidate
                        break
            left, right = tokens[start].start(), tokens[stop - 1].end()
            text = page[left:right]
            identity = f"{document['document_id']}:{document.get('document_version', 1)}:{config_id}:{page_number}:{left}:{right}:{text}"
            result.append({
                "chunk_id": str(uuid.uuid5(uuid.NAMESPACE_URL, identity)),
                "document_id": document["document_id"],
                "document_version": document.get("document_version", 1),
                "filename": document["filename"], "text": text,
                "source_spans": [{"page_number": page_number, "start_offset": left,
                                  "end_offset": right, "quote": text}],
                "chunking_config_id": config_id,
            })
            if stop == len(tokens):
                break
            start = max(start + 1, stop - overlap)
    return result
