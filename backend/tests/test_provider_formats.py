"""OpenAI-compatible/Gemini format variants, bounded repair, strict source scope."""

import copy
import json
import socket
from types import SimpleNamespace

import httpx
import pytest

from app.errors import ApiError
from app.generation import Generator


VALID = {"status": "answered", "answer": "Hồ sơ được xử lý trong 5 ngày. [src_001]", "source_ids": ["src_001"]}


def generator():
    return Generator(
        SimpleNamespace(
            generation_backend="api",
            context_char_budget=1000,
            llm_base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            llm_model="gemini-test",
            llm_api_key="private-test-key",
            llm_timeout=60,
        )
    )


def hits():
    text = "Hồ sơ được xử lý trong 5 ngày."
    return [
        {
            "chunk_id": "c1",
            "document_id": "doc1",
            "document_version": 1,
            "filename": "test.pdf",
            "source_spans": [{"page_number": 2, "start_offset": 0, "end_offset": len(text), "quote": text}],
        }
    ]


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))]
    )


def completion(content=None, **choice):
    return {"choices": [{"message": {"content": content}, **choice}]}


def provider(monkeypatch, responses):
    calls = []

    def post(url, **kwargs):
        calls.append(copy.deepcopy(kwargs))
        assert len(calls) <= len(responses), "Unexpected extra provider request"
        status, data = responses[len(calls) - 1]
        return httpx.Response(status, request=httpx.Request("POST", url), json=data)

    monkeypatch.setattr(httpx, "post", post)
    return calls


@pytest.mark.parametrize(
    "content",
    [
        json.dumps(VALID),
        "```json\n" + json.dumps(VALID) + "\n```",
        [{"type": "text", "text": json.dumps(VALID)}],
        json.dumps({**VALID, "confidence": 0.99, "citations": [{"page_number": 999, "quote": "invented"}]}),
        json.dumps({"status": "answered", "answer": VALID["answer"]}),
        json.dumps({**VALID, "source_ids": "src_001"}),
        json.dumps({**VALID, "source_ids": ["src_001", "src_001"]}),
        json.dumps({**VALID, "status": " ANSWERED "}),
    ],
)
def test_safe_variants_use_backend_citations(monkeypatch, content):
    calls = provider(monkeypatch, [(200, completion(content))])
    result = generator().answer("Thời gian xử lý?", hits(), {})
    assert result["status"] == "answered"
    assert result["citations"][0]["page_number"] == 2
    assert result["citations"][0]["quote"] == hits()[0]["source_spans"][0]["quote"]
    assert result["confidence"] is None
    assert "private-test-key" not in json.dumps(result)
    assert len(calls) == 1
    schema = calls[0]["json"]["response_format"]["json_schema"]
    assert schema["strict"] is True
    assert schema["schema"]["properties"]["source_ids"]["items"]["enum"] == ["src_001"]


def test_already_parsed_content(monkeypatch):
    provider(monkeypatch, [(200, {"choices": [{"message": {"content": None, "parsed": VALID}}]})])
    assert generator().answer("Thời gian?", hits(), {})["status"] == "answered"


@pytest.mark.parametrize(
    "bad",
    [
        {"answer": "Missing status. [src_001]", "source_ids": ["src_001"]},
        {"status": "answered", "answer": ["Wrong type"], "source_ids": ["src_001"]},
        ["not an answer object"],
    ],
)
def test_bad_schema_is_repaired_once(monkeypatch, bad):
    calls = provider(monkeypatch, [(200, completion(json.dumps(bad))), (200, completion(json.dumps(VALID)))])
    result = generator().answer("Thời gian?", hits(), {})
    assert len(calls) == 2 and result["retrieval_trace"]["response_repaired"] is True
    assert result["retrieval_trace"]["generation_attempts"] == 2
    assert len(calls[1]["json"]["messages"]) == 3


def test_invalid_json_repair_does_not_emit_raw_provider_body(monkeypatch):
    raw = "unparseable private-test-key provider text"
    calls = provider(monkeypatch, [(200, completion(raw)), (200, completion(raw))])
    with pytest.raises(ApiError) as caught:
        generator().answer("Thời gian?", hits(), {})
    assert caught.value.code == "LLM_BAD_RESPONSE"
    assert len(calls) == 2
    assert raw not in caught.value.message
    assert raw not in json.dumps(calls[1]["json"])


def test_unknown_source_never_becomes_valid_by_normalization(monkeypatch):
    forged = {"status": "answered", "answer": "Bịa nguồn [src_999]"}
    calls = provider(monkeypatch, [(200, completion(json.dumps(forged)))] * 2)
    with pytest.raises(ApiError) as caught:
        generator().answer("Thời gian?", hits(), {})
    assert caught.value.code == "CITATION_VALIDATION_FAILED" and len(calls) == 2


def test_unsupported_schema_negotiation(monkeypatch):
    calls = provider(
        monkeypatch,
        [
            (400, {"error": {"message": "response_format json_schema is not supported"}}),
            (200, completion(json.dumps(VALID))),
        ],
    )
    result = generator().answer("Thời gian?", hits(), {})
    assert calls[0]["json"]["response_format"]["type"] == "json_schema"
    assert calls[1]["json"]["response_format"]["type"] == "json_object"
    assert result["retrieval_trace"]["response_format"] == "json_object"


@pytest.mark.parametrize("status", [400, 401, 403, 429, 500])
def test_provider_errors_do_not_trigger_schema_repair(monkeypatch, status):
    calls = provider(monkeypatch, [(status, {"error": {"message": "private-test-key"}})])
    with pytest.raises(ApiError) as caught:
        generator().answer("Thời gian?", hits(), {})
    assert len(calls) == 1 and "private-test-key" not in caught.value.message


@pytest.mark.parametrize("reason,code", [("length", "LLM_OUTPUT_TRUNCATED"), ("content_filter", "LLM_REFUSED")])
def test_truncated_or_filtered_answers_are_not_parsed_or_repaired(monkeypatch, reason, code):
    calls = provider(monkeypatch, [(200, completion(json.dumps(VALID), finish_reason=reason))])
    with pytest.raises(ApiError) as caught:
        generator().answer("Thời gian?", hits(), {})
    assert caught.value.code == code and len(calls) == 1


def test_refusal_not_repaired(monkeypatch):
    calls = provider(monkeypatch, [(200, {"choices": [{"message": {"content": None, "refusal": "blocked"}}]})])
    with pytest.raises(ApiError) as caught:
        generator().answer("Thời gian?", hits(), {})
    assert caught.value.code == "LLM_REFUSED" and len(calls) == 1


def test_insufficient_evidence_with_null_source_ids(monkeypatch):
    provider(
        monkeypatch,
        [(200, completion(json.dumps({"status": "insufficient_evidence", "answer": "Chưa đủ", "source_ids": None})))],
    )
    result = generator().answer("Thời gian?", hits(), {})
    assert result["status"] == "insufficient_evidence" and result["citations"] == []


def test_negotiation_plus_repair_has_at_most_three_requests(monkeypatch):
    bad = completion(json.dumps({"answer": "missing required status"}))
    calls = provider(monkeypatch, [(422, {"error": {"message": "json_schema not supported"}}), (200, bad), (200, bad)])
    with pytest.raises(ApiError) as caught:
        generator().answer("Thời gian?", hits(), {})
    assert len(calls) == 3
    assert caught.value.code == "LLM_BAD_RESPONSE"
    assert {"field": "status", "reason": "required"} in caught.value.details


def test_format_repair_shares_original_timeout_budget(monkeypatch):
    # One initial deadline + before first request + before repair request.
    import app.generation as module

    clock = iter([0, 1, 61])
    monkeypatch.setattr(module.time, "monotonic", lambda: next(clock))
    calls = provider(monkeypatch, [(200, completion("bad json"))])
    with pytest.raises(ApiError) as caught:
        generator().answer("Thời gian?", hits(), {})
    assert caught.value.code == "UPSTREAM_TIMEOUT" and len(calls) == 1
    assert calls[0]["timeout"] == 59


def test_chat_endpoint_repairs_gemini_response_with_tab_model_settings(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app

    app = create_app(Settings(data_dir=tmp_path))
    trace = {
        "resolved_index_version": "idx-1",
        "corpus_snapshot_id": "corpus-1",
        "embedding_model_version": "hash",
        "chunking_config_id": "chunk-1",
        "effective_config": {"dense": True, "bm25": True, "reranking": True, "top_k": 5},
        "candidate_count": 1,
        "reranked_count": 1,
        "returned_count": 1,
        "context_chunk_count": 0,
    }
    store = app.state.store
    monkeypatch.setattr(store, "pin", lambda *a: ("idx-1", tmp_path))
    monkeypatch.setattr(store, "recheck", lambda *a: None)
    monkeypatch.setattr(store.engine, "search", lambda *a: (hits(), trace))
    calls = provider(
        monkeypatch,
        [
            (200, completion(json.dumps({"answer": "missing status"}))),
            (200, completion("```json\n" + json.dumps(VALID) + "\n```")),
        ],
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/chat",
            json={
                "question": "Thời gian xử lý?",
                "generation_config": {
                    "backend": "api",
                    "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                    "model": "gemini-test",
                    "api_key": "private-test-key",
                },
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "answered"
    assert response.json()["retrieval_trace"]["response_repaired"] is True
    assert len(calls) == 2 and "private-test-key" not in response.text
    assert response.json()["request_id"] == response.headers["X-Request-ID"]
