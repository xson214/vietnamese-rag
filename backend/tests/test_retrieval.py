import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from app.chunking import chunk_pages
from app.errors import ApiError
from app.retrieval import Engine


def settings(**updates):
    return SimpleNamespace(**dict({
        "embedding_backend": "hash", "embedding_model": "demo", "embedding_revision": "1",
        "reranker_backend": "lexical", "reranker_model": "demo", "reranker_revision": "1",
        "qdrant_url": None,
    }, **updates))


class ChunkingTests(unittest.TestCase):
    def test_exact_unicode_provenance_and_determinism(self):
        pages = ["  Quy định tiếng Việt 😀.\n\nThủ tục đăng ký học phần tại trường.\nXử lý hồ sơ.",
                 "Mỗi hồ sơ cần có chữ ký xác nhận."]
        for strategy in ("fixed", "recursive", "heading"):
            chunks = chunk_pages({"document_id": "doc_a", "filename": "nội quy.pdf"},
                                 pages, strategy, size=8, overlap=2)
            self.assertEqual(chunks, chunk_pages({"document_id": "doc_a", "filename": "nội quy.pdf"},
                                                pages, strategy, size=8, overlap=2))
            self.assertGreater(len(chunks), 2)
            for chunk in chunks:
                for span in chunk["source_spans"]:
                    page = pages[span["page_number"] - 1]
                    self.assertEqual(span["quote"], page[span["start_offset"]:span["end_offset"]])
                    self.assertEqual(chunk["text"], span["quote"])

    def test_invalid_chunking_config(self):
        with self.assertRaises(ValueError):
            chunk_pages({}, ["text"], size=5, overlap=5)


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / "idx_001"
        self.engine = Engine(settings())
        self.chunks = []
        for doc_id, text in [("doc_a", "Sinh viên nộp hồ sơ đăng ký học phần trước ngày 15 tháng 9."),
                             ("doc_b", "Hệ thống sao lưu dữ liệu mỗi ngày và bảo vệ tài khoản người dùng."),
                             ("doc_c", "Mèo là động vật có vú, thường được nuôi trong gia đình.")]:
            self.chunks += chunk_pages({"document_id": doc_id, "document_version": 1,
                                        "filename": doc_id + ".pdf"}, [text])
        self.manifest = self.engine.build("idx_001", self.chunks, self.directory)

    def tearDown(self):
        self.temp.cleanup()

    def test_hybrid_rerank_is_tagged_and_relevant(self):
        hits, trace = self.engine.search(self.directory, "nộp hồ sơ đăng ký học phần", {})
        self.assertEqual(hits[0]["document_id"], "doc_a")
        self.assertTrue(trace["demo_backends"])
        self.assertEqual(trace["resolved_index_version"], "idx_001")
        self.assertEqual(trace["candidate_count"], trace["reranked_count"])
        self.assertGreater(hits[0]["scores"]["bm25"], 0)
        self.assertGreater(hits[0]["scores"]["fusion"], 0)
        self.assertIsNotNone(hits[0]["scores"]["rerank"])

    def test_scope_applied_to_both_retrievers(self):
        hits, _ = self.engine.search(self.directory, "hồ sơ đăng ký học phần", {}, ["doc_b"])
        self.assertEqual({h["document_id"] for h in hits}, {"doc_b"})

    def test_bm25_only_does_not_call_encoder_and_points_are_not_confidence(self):
        self.engine._encode = lambda *a, **kw: self.fail("BM25 should not invoke encoder")
        hits, trace = self.engine.search(self.directory, "hồ sơ", {"dense": False, "reranking": False})
        self.assertEqual(hits[0]["document_id"], "doc_a")
        self.assertIsNone(hits[0]["scores"]["dense"])
        self.assertIsNone(hits[0]["scores"]["fusion"])
        self.assertIsNone(hits[0]["scores"]["rerank"])
        self.assertEqual(trace["reranked_count"], 0)

    def test_no_keyword_matches_is_empty_for_bm25(self):
        hits, _ = self.engine.search(self.directory, "xyz987654", {"dense": False})
        self.assertEqual(hits, [])

    def test_generation_cannot_be_overwritten(self):
        with self.assertRaises(ApiError) as caught:
            self.engine.build("idx_001", self.chunks, self.directory)
        self.assertEqual(caught.exception.status, 409)

    def test_tampered_snapshot_is_rejected(self):
        path = self.directory / "chunks.json"
        chunks = json.loads(path.read_text(encoding="utf-8"))
        chunks[0]["text"] = "Tampered source"
        path.write_text(json.dumps(chunks), encoding="utf-8")
        with self.assertRaises(ApiError) as caught:
            self.engine.search(self.directory, "hồ sơ", {})
        self.assertEqual(caught.exception.status, 503)

    def test_query_uses_pinned_manifest_not_new_config(self):
        other_engine = Engine(settings(embedding_backend="sentence_transformers", embedding_model="different-model"))
        hits, _ = other_engine.search(self.directory, "hồ sơ", {})
        self.assertEqual(hits[0]["document_id"], "doc_a")

    def test_disabled_both_retrievers_rejected(self):
        with self.assertRaises(ApiError):
            self.engine.search(self.directory, "hồ sơ", {"dense": False, "bm25": False})

    def test_corpus_identity_independent_of_chunk_boundaries(self):
        alternate = []
        for chunk in self.chunks:
            alternate += chunk_pages(chunk, [chunk["text"]], strategy="fixed", size=5, overlap=1)
        manifest = self.engine.build("idx_002", alternate, Path(self.temp.name) / "idx_002")
        self.assertEqual(manifest["corpus_snapshot_id"], self.manifest["corpus_snapshot_id"])
        self.assertNotEqual(manifest["chunks_sha256"], self.manifest["chunks_sha256"])


if __name__ == "__main__":
    unittest.main()
