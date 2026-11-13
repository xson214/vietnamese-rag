"""Exercise Qdrant REST adapters against an in-memory HTTP double.

These verify request/response integration, not a real Qdrant server deployment.
"""

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx
import numpy as np

from app.chunking import chunk_pages
from app.errors import ApiError
from app.retrieval import Engine


class QdrantHttpDouble:
    """Small fake implementing the REST surface Engine actually consumes."""

    def __init__(self):
        self.collections = {}
        self.calls = []
        self.count_adjustment = 0
        self.query_override = None

    @staticmethod
    def response(method, url, code=200, result=True):
        return httpx.Response(code, json={"result": result, "status": "ok"},
                              request=httpx.Request(method, url))

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": copy.deepcopy(json),
                           "headers": copy.deepcopy(headers), "timeout": timeout})
        path = urlsplit(url).path.strip("/").split("/")
        if len(path) < 2 or path[0] != "collections":
            return self.response(method, url, 404)
        name = path[1]
        if method == "PUT" and len(path) == 2:
            self.collections[name] = {"config": json, "points": {}}
            return self.response(method, url)
        if method == "DELETE" and len(path) == 2:
            if self.collections.pop(name, None) is None:
                return self.response(method, url, 404)
            return self.response(method, url)
        if name not in self.collections:
            return self.response(method, url, 404)
        collection = self.collections[name]
        if method == "PUT" and path[2:] == ["points"]:
            for point in json["points"]:
                collection["points"][point["id"]] = copy.deepcopy(point)
            return self.response(method, url, result={"status": "completed"})
        if method == "GET" and len(path) == 2:
            return self.response(method, url, result={
                "points_count": len(collection["points"]) + self.count_adjustment})
        if method == "POST" and path[2:] == ["points", "query"]:
            if self.query_override is not None:
                return self.response(method, url, result={"points": self.query_override})
            allowed = None
            if "filter" in json:
                condition = json["filter"]["must"][0]
                if condition["key"] != "document_id":
                    raise AssertionError("Unexpected filter field")
                allowed = set(condition["match"]["any"])
            query = np.array(json["query"])
            points = []
            for point in collection["points"].values():
                if allowed is not None and point["payload"]["document_id"] not in allowed:
                    continue
                vector = np.array(point["vector"])
                denominator = np.linalg.norm(vector) * np.linalg.norm(query)
                score = float(vector @ query) / denominator if denominator else 0.0
                points.append({"id": point["id"], "score": score})
            points.sort(key=lambda point: (-point["score"], point["id"]))
            return self.response(method, url, result={"points": points[:json["limit"]]})
        return self.response(method, url, 404)


class QdrantAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / "idx_qdrant"
        self.settings = SimpleNamespace(
            embedding_backend="hash", embedding_model="demo", embedding_revision="1",
            reranker_backend="lexical", reranker_model="demo", reranker_revision="1",
            qdrant_url="http://qdrant.test:6333/", qdrant_api_key="fixture-not-a-secret")
        self.engine = Engine(self.settings)
        self.http = QdrantHttpDouble()
        self.patcher = patch("app.retrieval.httpx.request", side_effect=self.http.request)
        self.patcher.start()
        self.chunks = []
        for ident, text in [("doc_a", "Hồ sơ học phần nộp trước ngày 15 tháng 9."),
                            ("doc_b", "Sao lưu dữ liệu hệ thống mỗi ngày vào lúc 22 giờ.")]:
            self.chunks.extend(chunk_pages({"document_id": ident, "document_version": 1,
                                            "filename": ident + ".pdf"}, [text]))

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def build(self):
        return self.engine.build("idx_qdrant", self.chunks, self.directory)

    def test_build_uploads_exact_chunk_ids_and_vectors_in_bounded_batches(self):
        # More than 64 points exercises the second batch and vector row offsets.
        self.chunks = chunk_pages(
            {"document_id": "doc_many", "document_version": 1, "filename": "many.pdf"},
            [f"Dòng {i} có nội dung riêng biệt về hồ sơ." for i in range(70)])
        manifest = self.build()
        collection = self.http.collections[manifest["collection"]]
        self.assertEqual(manifest["storage_backend"], "qdrant")
        self.assertEqual(collection["config"]["vectors"], {"size": 384, "distance": "Cosine"})
        self.assertEqual(set(collection["points"]), {chunk["chunk_id"] for chunk in self.chunks})
        self.assertEqual(manifest["chunk_count"], 70)
        batches = [call for call in self.http.calls if call["method"] == "PUT" and "/points?" in call["url"]]
        self.assertEqual([len(call["json"]["points"]) for call in batches], [64, 6])
        stored_chunks = json.loads((self.directory / "chunks.json").read_text(encoding="utf-8"))
        vectors = np.load(self.directory / "vectors.npy", allow_pickle=False)
        for chunk, vector in zip(stored_chunks, vectors):
            point = collection["points"][chunk["chunk_id"]]
            np.testing.assert_allclose(point["vector"], vector)
            self.assertEqual(point["payload"]["document_id"], chunk["document_id"])
        self.assertTrue(all(call["headers"]["api-key"] == "fixture-not-a-secret" for call in self.http.calls))
        self.assertTrue(all(call["timeout"] == 60 for call in self.http.calls))

    def test_query_sends_scope_filter_and_returns_only_allowed_document(self):
        manifest = self.build()
        hits, trace = self.engine.search(self.directory, "hồ sơ học phần", {}, ["doc_b"])
        self.assertEqual({hit["document_id"] for hit in hits}, {"doc_b"})
        call = next(call for call in self.http.calls if call["method"] == "POST")
        self.assertEqual(call["json"]["filter"], {
            "must": [{"key": "document_id", "match": {"any": ["doc_b"]}}]})
        self.assertEqual(call["json"]["limit"], 20)
        self.assertEqual(len(call["json"]["query"]), 384)
        self.assertFalse(call["json"]["with_payload"])
        self.assertEqual(trace["resolved_index_version"], manifest["index_version"])
        self.assertIsNotNone(hits[0]["scores"]["dense"])

    def test_query_unscoped_relevance_and_generation_isolation(self):
        first = self.build()
        second_directory = Path(self.temp.name) / "idx_second"
        second = self.engine.build("idx_second", self.chunks, second_directory)
        self.assertNotEqual(first["collection"], second["collection"])
        hits, _ = self.engine.search(self.directory, "hồ sơ học phần", {"bm25": False})
        self.assertEqual(hits[0]["document_id"], "doc_a")
        query = next(call for call in self.http.calls if call["method"] == "POST")
        self.assertIn(first["collection"], query["url"])
        self.assertNotIn("filter", query["json"])
        self.engine.delete(self.directory)
        self.assertIn(second["collection"], self.http.collections)

    def test_cleanup_repeated_404_is_successful(self):
        manifest = self.build()
        self.engine.delete(self.directory)
        self.engine.delete(self.directory)
        self.assertNotIn(manifest["collection"], self.http.collections)
        calls = [call for call in self.http.calls if call["method"] == "DELETE"]
        self.assertEqual(len(calls), 2)

    def test_count_mismatch_prevents_manifest_publication_and_cleans_collection(self):
        self.http.count_adjustment = -1
        with self.assertRaises(ApiError) as caught:
            self.build()
        self.assertEqual(caught.exception.status, 503)
        self.assertFalse((self.directory / "manifest.json").exists())
        self.assertEqual(self.http.collections, {})
        # A crash-safe resource descriptor remains usable after failed build.
        self.assertTrue((self.directory / "resources.json").exists())
        self.engine.delete(self.directory)

    def test_foreign_or_out_of_scope_qdrant_point_rejected(self):
        self.build()
        known_a = next(chunk["chunk_id"] for chunk in self.chunks if chunk["document_id"] == "doc_a")
        for ident in ("00000000-0000-0000-0000-000000000000", known_a):
            with self.subTest(point_id=ident):
                self.http.query_override = [{"id": ident, "score": 0.99}]
                with self.assertRaises(ApiError) as caught:
                    self.engine.search(self.directory, "hồ sơ", {}, ["doc_b"])
                self.assertEqual(caught.exception.status, 503)

    def test_server_transport_error_does_not_fallback_to_local_vectors(self):
        self.build()
        with patch("app.retrieval.httpx.request", side_effect=httpx.ConnectError("fixture offline")):
            with self.assertRaises(ApiError) as caught:
                self.engine.search(self.directory, "hồ sơ", {})
        self.assertEqual(caught.exception.status, 503)
        self.assertEqual(caught.exception.code, "DEPENDENCY_UNAVAILABLE")

    def test_empty_generation_has_zero_points_and_empty_search(self):
        self.chunks = []
        manifest = self.build()
        self.assertEqual(self.http.collections[manifest["collection"]]["points"], {})
        hits, trace = self.engine.search(self.directory, "hồ sơ", {})
        self.assertEqual(hits, [])
        self.assertEqual(trace["candidate_count"], 0)


if __name__ == "__main__":
    unittest.main()
