"""Metrics over canonical source spans, independent of changing chunk IDs."""

from __future__ import annotations


def _same_page(left: dict, right: dict) -> bool:
    return all(left.get(key) == right.get(key) for key in (
        "document_id", "document_version", "page_number"
    ))


def hit_spans(hit: dict) -> list[dict]:
    return [
        {**span, "document_id": hit["document_id"], "document_version": hit["document_version"]}
        for span in hit.get("source_spans", [])
    ]


def covered(gold: dict, spans: list[dict]) -> bool:
    """Union adjacent/overlapping intervals on the same version and page."""
    position = gold["start_offset"]
    for span in sorted(
        (item for item in spans if _same_page(gold, item)),
        key=lambda item: item["start_offset"],
    ):
        if span["start_offset"] > position:
            break
        if span["end_offset"] > position:
            position = span["end_offset"]
        if position >= gold["end_offset"]:
            return True
    return False


def evidence_recall(hits: list[dict], evidence_sets: list[dict], k: int = 5) -> float | None:
    if not evidence_sets:
        return None
    spans = [span for hit in hits[:k] for span in hit_spans(hit)]
    return max(
        sum(covered(gold, spans) for gold in item["spans"]) / len(item["spans"])
        for item in evidence_sets if item["spans"]
    )


def reciprocal_rank(hits: list[dict], evidence_sets: list[dict], k: int = 10) -> float | None:
    if not evidence_sets:
        return None
    gold = [span for group in evidence_sets for span in group["spans"]]
    for rank, hit in enumerate(hits[:k], start=1):
        if any(covered(span, hit_spans(hit)) for span in gold):
            return 1 / rank
    return 0.0


def safe_div(numerator: float, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def latency_summary(values: list[float]) -> dict:
    values = sorted(values)
    if not values:
        return {"count": 0, "p50_seconds": None, "p95_seconds": None}

    def percentile(p):
        position = (len(values) - 1) * p
        low = int(position)
        high = min(low + 1, len(values) - 1)
        return values[low] + (values[high] - values[low]) * (position - low)

    return {"count": len(values), "p50_seconds": percentile(.5), "p95_seconds": percentile(.95)}


def summarize(rows: list[dict]) -> dict:
    counts = {"tp": 0, "fp": 0, "tn": 0, "fn": 0, "error_answerable": 0, "error_unanswerable": 0}
    retrieval = [row for row in rows if row["answerable"]]
    for row in rows:
        outcome = row.get("chat", {}).get("status")
        if outcome not in {"answered", "insufficient_evidence"}:
            counts["error_answerable" if row["answerable"] else "error_unanswerable"] += 1
        elif outcome == "insufficient_evidence":
            counts["fp" if row["answerable"] else "tp"] += 1
        else:
            counts["tn" if row["answerable"] else "fn"] += 1
    tp, fp, tn, fn = (counts[key] for key in ("tp", "fp", "tn", "fn"))
    return {
        "question_count": len(rows), "answerable_count": len(retrieval),
        "evidence_recall_at_5": safe_div(sum(row.get("recall_at_5") or 0 for row in retrieval), len(retrieval)),
        "mrr_at_10": safe_div(sum(row.get("rr_at_10") or 0 for row in retrieval), len(retrieval)),
        "all_evidence_at_5": safe_div(sum(row.get("recall_at_5") == 1 for row in retrieval), len(retrieval)),
        "retrieval_error_count": sum("error" in row.get("search", {}) for row in rows),
        "abstention": {
            **counts,
            "precision": safe_div(tp, tp + fp),
            "recall_valid": safe_div(tp, tp + fn),
            "recall_all": safe_div(tp, tp + fn + counts["error_unanswerable"]),
            "false_abstention_rate_all": safe_div(fp, fp + tn + counts["error_answerable"]),
        },
        "manual_scores_required": ["answer_correctness", "citation_precision", "citation_coverage"],
        "latency_including_errors": {
            route: latency_summary([
                row[route]["elapsed_seconds"] for row in rows
                if "elapsed_seconds" in row.get(route, {})
            ]) for route in ("search", "chat")
        },
    }
