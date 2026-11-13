from evaluation.metrics import covered, evidence_recall, reciprocal_rank, summarize


def span(start, end, doc="doc-1"):
    return {"document_id": doc, "document_version": 1, "page_number": 1, "start_offset": start, "end_offset": end}


def hit(start, end):
    return {"document_id": "doc-1", "document_version": 1, "source_spans": [span(start, end)]}


def test_union_is_not_confused_with_single_hit_relevance():
    gold = [{"spans": [span(0, 10)]}]
    hits = [hit(0, 5), hit(5, 10)]
    assert evidence_recall(hits, gold) == 1
    assert reciprocal_rank(hits, gold) == 0
    assert not covered(span(0, 10), [span(0, 5), span(6, 10)])


def test_alternative_evidence_sets_and_document_version():
    gold = [{"spans": [span(0, 5), span(10, 15)]}, {"spans": [span(20, 25)]}]
    assert evidence_recall([hit(20, 25)], gold) == 1
    assert evidence_recall([hit(0, 5)], gold) == 0.5
    wrong = span(0, 5)
    wrong["document_version"] = 2
    assert not covered(wrong, [span(0, 5)])


def test_errors_do_not_disappear_from_abstention_recall():
    rows = [
        {"answerable": False, "chat": {"status": "insufficient_evidence"}},
        {"answerable": False, "chat": {"error": {"code": "TIMEOUT"}}},
        {"answerable": True, "chat": {"status": "answered"}, "recall_at_5": 1, "rr_at_10": 0.5},
    ]
    result = summarize(rows)
    assert result["abstention"]["recall_valid"] == 1
    assert result["abstention"]["recall_all"] == 0.5
    assert result["abstention"]["error_unanswerable"] == 1
    assert summarize([])["abstention"]["precision"] is None
