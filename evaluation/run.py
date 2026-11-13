"""CLI: python -m evaluation.run --help (run from repository root)."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .metrics import evidence_recall, reciprocal_rank, summarize


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_dataset(dataset: dict, allow_fixtures: bool) -> None:
    if dataset.get("fixture_only") and not allow_fixtures:
        raise ValueError("Demo fixtures require --allow-fixtures; they are not a research gold dataset.")
    rows = dataset.get("questions")
    if not dataset.get("dataset_version") or not isinstance(rows, list) or not rows:
        raise ValueError("Dataset must include dataset_version and nonempty questions.")
    seen = set()
    for row in rows:
        qid = row.get("question_id")
        if not qid or qid in seen or not row.get("question", "").strip() or type(row.get("answerable")) is not bool:
            raise ValueError("Invalid or duplicate question_id/question/answerable.")
        seen.add(qid)
        sets = row.get("evidence_sets", [])
        if row["answerable"] != bool(sets):
            raise ValueError(f"{qid}: answerable must agree with nonempty evidence_sets.")
        for group in sets:
            if not group.get("spans"):
                raise ValueError(f"{qid}: evidence group cannot be empty.")
            for span in group["spans"]:
                if (
                    not span.get("document_id") or span.get("document_version", 0) < 1
                    or span.get("page_number", 0) < 1 or span.get("start_offset", -1) < 0
                    or span.get("end_offset", 0) <= span["start_offset"]
                    or len(span.get("quote", "")) != span["end_offset"] - span["start_offset"]
                ):
                    raise ValueError(f"{qid}: invalid gold source span.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New run directory; must not already exist.")
    parser.add_argument("--base-url", default="http://localhost:8000/api/v1")
    parser.add_argument("--index-version", required=True, help="Published, pinned generation ID.")
    parser.add_argument("--document-map", type=Path, help='JSON mapping fixture document IDs to uploaded IDs.')
    parser.add_argument("--retrieval-config", type=Path, help="JSON with dense/bm25/reranking flags; top_k overridden to 10 for retrieval.")
    parser.add_argument("--run-metadata", type=Path, help="JSON with LLM/prompt/dependency/hardware revisions not exposed by the API. Never include secrets.")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--allow-fixtures", action="store_true")
    args = parser.parse_args()
    dataset = read_json(args.dataset)
    validate_dataset(dataset, args.allow_fixtures)
    mapping = read_json(args.document_map) if args.document_map else {}
    config = read_json(args.retrieval_config) if args.retrieval_config else {"dense": True, "bm25": True, "reranking": True, "top_k": 5}
    config = {"dense": True, "bm25": True, "reranking": True, "top_k": 5, **config}
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        git_revision = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False).stdout.strip() or None
    except OSError:
        git_revision = None
    manifest = {
        "started_at": datetime.now(timezone.utc).isoformat(), "dataset_version": dataset["dataset_version"],
        "dataset_sha256": digest(dataset), "document_mapping": mapping,
        "fixture_only": bool(dataset.get("fixture_only")), "index_version": args.index_version,
        "retrieval_config": config, "code_revision": git_revision,
        "platform": platform.platform(), "python": platform.python_version(),
        "concurrency": 1, "timeout_seconds": args.timeout, "retry_count": 0,
        "valid": True, "invalid_reason": None,
        "manual_review_required": True,
        "additional_metadata": read_json(args.run_metadata) if args.run_metadata else {},
    }
    records = []
    expected_trace = {}

    def call(client, route, payload):
        before = time.perf_counter()
        try:
            response = client.post(args.base_url.rstrip("/") + route, json=payload)
            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("API response is not a JSON object.")
            if response.is_error:
                body = {"error": body.get("error", {"code": "HTTP_ERROR"}), "http_status": response.status_code}
            else:
                trace = body.get("retrieval_trace", {})
                pinned = trace.get("resolved_index_version")
                corpus = trace.get("corpus_snapshot_id")
                if pinned != args.index_version or not corpus:
                    raise ValueError("Response generation/corpus does not match pinned benchmark.")
                signature = {key: trace.get(key) for key in (
                    "resolved_index_version", "corpus_snapshot_id", "embedding_model_version", "chunking_config_id"
                )}
                if expected_trace and signature != expected_trace:
                    raise ValueError("Corpus/model/chunking changed during benchmark.")
                expected_trace.update(signature)
            if body.get("error", {}).get("code") in {"INDEX_VERSION_UNAVAILABLE", "SOURCE_SET_CHANGED", "INDEX_VERSION_NOT_FOUND"}:
                manifest["valid"] = False
                manifest["invalid_reason"] = "Pinned generation was revoked or unavailable."
        except (httpx.RequestError, ValueError) as exc:
            if isinstance(exc, ValueError) and not isinstance(exc, json.JSONDecodeError):
                manifest["valid"] = False
                manifest["invalid_reason"] = str(exc)
            body = {"error": {"code": "RUNNER_ERROR", "message": str(exc)}}
        body["elapsed_seconds"] = time.perf_counter() - before
        return body

    with httpx.Client(timeout=args.timeout) as client:
        for gold in dataset["questions"]:
            # Copy through JSON so ID rebinding cannot mutate the dataset hash.
            row = json.loads(json.dumps(gold))
            for group in row.get("evidence_sets", []):
                for span in group["spans"]:
                    span["document_id"] = mapping.get(span["document_id"], span["document_id"])
            common = {"index_version": args.index_version}
            if row.get("document_ids"):
                common["document_ids"] = [mapping.get(item, item) for item in row["document_ids"]]
            search = call(client, "/search", {**common, "query": row["question"], "retrieval_config": {**config, "top_k": 10}})
            chat = call(client, "/chat", {**common, "question": row["question"], "retrieval_config": config}) if manifest["valid"] else {"error": {"code": "RUN_INVALID"}}
            hits = search.get("hits", [])
            records.append({
                "question_id": row["question_id"], "question": row["question"], "answerable": row["answerable"],
                "search": search, "chat": chat,
                "recall_at_5": evidence_recall(hits, row.get("evidence_sets", []), 5),
                "rr_at_10": reciprocal_rank(hits, row.get("evidence_sets", []), 10),
                "manual_review": {"correctness": None, "citation_precision": None, "citation_coverage": None},
            })
            if not manifest["valid"]:
                break
        # A final request detects revocation after the last measured answer.
        if manifest["valid"] and records:
            probe = call(client, "/search", {"query": dataset["questions"][0]["question"], "index_version": args.index_version, "retrieval_config": {**config, "top_k": 10}})
            if "error" in probe:
                manifest["valid"] = False
                manifest["invalid_reason"] = "Final generation check failed; cannot verify stable run."
        manifest["completed_at"] = datetime.now(timezone.utc).isoformat()
        manifest["resolved_generation"] = expected_trace
    summary = summarize(records)
    summary["valid"] = manifest["valid"]
    summary["fixture_only"] = manifest["fixture_only"]
    summary["planned_question_count"] = len(dataset["questions"])
    for name, value in [("manifest.json", manifest), ("predictions.json", records), ("summary.json", summary)]:
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if manifest["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
