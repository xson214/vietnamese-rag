"""Immutable retrieval generations, BM25, dense retrieval, RRF and reranking.

The hash/lexical backends are explicitly labelled offline demo baselines.
Sentence Transformers/CrossEncoder run real neural models when configured.
There is no automatic fallback from one backend to another.
"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import unicodedata

import httpx
import numpy as np

from .errors import ApiError


def tokenize(text: str) -> list[str]:
    return re.findall(r"\w+", unicodedata.normalize("NFC", text).lower(), re.UNICODE)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


class Engine:
    def __init__(self, settings):
        self.settings = settings
        self._models = {}
        self._model_lock = threading.RLock()

    def _embedding_spec(self):
        if self.settings.embedding_backend == "hash":
            return {"backend": "hash", "model": "signed-word-char3-384", "revision": "1",
                    "normalization": "l2", "implementation": "dense-v1", "dimension": 384}
        return {"backend": self.settings.embedding_backend,
                "model": self.settings.embedding_model,
                "revision": self.settings.embedding_revision,
                "normalization": "l2", "implementation": "dense-v1",
                "dimension": 384 if self.settings.embedding_backend == "hash" else None}

    def _pin_revision(self, spec, kind):
        if spec["backend"] in {"hash", "lexical"}:
            return spec
        model = self._model(spec, kind)
        try:
            config = model[0].auto_model.config if kind == "embedding" else model.model.config
            commit = getattr(config, "_commit_hash", None)
        except (AttributeError, KeyError, TypeError):
            commit = None
        if commit:
            spec = dict(spec, revision=commit)
            self._models[(kind, spec["model"], commit)] = model
        elif not re.fullmatch(r"[0-9a-f]{40}", spec.get("revision") or ""):
            raise ApiError(503, "CONFIGURATION_MISSING",
                           "Không xác định được model revision bất biến; cấu hình commit hash cụ thể.")
        return spec

    def _model(self, spec: dict, kind: str):
        key = (kind, spec["model"], spec.get("revision"))
        with self._model_lock:
            if key not in self._models:
                try:
                    from sentence_transformers import CrossEncoder, SentenceTransformer
                    cls = SentenceTransformer if kind == "embedding" else CrossEncoder
                    self._models[key] = cls(spec["model"], revision=spec.get("revision") or None,
                                            trust_remote_code=False)
                except Exception as exc:
                    raise ApiError(503, "DEPENDENCY_UNAVAILABLE",
                                   "Không tải được model retrieval đã cấu hình.", True) from exc
            return self._models[key]

    def _encode(self, texts: list[str], spec: dict, query=False) -> np.ndarray:
        if spec["backend"] == "hash":
            # Signed feature hashing of words + character ngrams. NOT semantic.
            vectors = np.zeros((len(texts), 384), dtype=np.float32)
            for row, text in enumerate(texts):
                words = tokenize(text)
                features = words + ["_".join(words[i:i + 2]) for i in range(len(words) - 1)]
                for word in words:
                    features.extend(word[i:i + 3] for i in range(max(0, len(word) - 2)))
                for feature, count in Counter(features).items():
                    digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
                    bucket = int.from_bytes(digest[:4], "little") % 384
                    vectors[row, bucket] += (1 if digest[4] & 1 else -1) * count
            norms = np.linalg.norm(vectors, axis=1, keepdims=True)
            return vectors / np.maximum(norms, 1e-12)
        if spec["backend"] != "sentence_transformers":
            raise ApiError(503, "CONFIGURATION_MISSING", "Embedding backend không hợp lệ.")
        model = self._model(spec, "embedding")
        prefix = "query: " if query else "passage: "
        inputs = [prefix + x if "e5" in spec["model"].lower() else x for x in texts]
        try:
            for text in inputs:
                if len(model.tokenizer.encode(text, truncation=False)) > model.max_seq_length:
                    raise ApiError(422, "MODEL_INPUT_TOO_LONG",
                                   "Text vượt giới hạn embedding; giảm kích thước chunk/câu hỏi.")
            if not inputs:
                return np.zeros((0, model.get_sentence_embedding_dimension()), dtype=np.float32)
            return np.asarray(model.encode(inputs, normalize_embeddings=True,
                                           show_progress_bar=False), dtype=np.float32)
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError(503, "DEPENDENCY_UNAVAILABLE", "Embedding model không thực hiện được yêu cầu.", True) from exc

    def _qdrant(self, method, path, body=None):
        url = getattr(self.settings, "qdrant_url", None)
        headers = {}
        if getattr(self.settings, "qdrant_api_key", None):
            headers["api-key"] = self.settings.qdrant_api_key
        try:
            response = httpx.request(method, url.rstrip("/") + path, json=body,
                                     headers=headers, timeout=60)
            if method == "DELETE" and response.status_code == 404:
                return {}
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ApiError(503, "DEPENDENCY_UNAVAILABLE", "Không truy cập được Qdrant.", True) from exc

    def build(self, index_version: str, chunks: list[dict], directory: Path) -> dict:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        if (directory / "manifest.json").exists():
            raise ApiError(409, "INDEX_VERSION_UNAVAILABLE", "Không ghi đè index generation đã dựng.")
        ids = [c["chunk_id"] for c in chunks]
        if len(set(ids)) != len(ids):
            raise ApiError(422, "INVALID_DOCUMENT", "Chunk ID bị trùng trong generation.")
        chunks = sorted(chunks, key=lambda c: (c["document_id"], c["chunk_id"]))
        for chunk in chunks:
            if not chunk["source_spans"] or any(
                    s["end_offset"] <= s["start_offset"] or
                    len(s["quote"]) != s["end_offset"] - s["start_offset"] or s["page_number"] < 1
                    for s in chunk["source_spans"]):
                raise ApiError(422, "INVALID_DOCUMENT", "Source span không hợp lệ.")
        spec = self._pin_revision(self._embedding_spec(), "embedding")
        vectors = self._encode([c["text"] for c in chunks], spec)
        spec["dimension"] = int(vectors.shape[1])
        corpus = sorted({(c["document_id"], c["document_version"]) for c in chunks})
        configs = sorted({c["chunking_config_id"] for c in chunks})
        collection = "rag_" + hashlib.sha256(index_version.encode()).hexdigest()[:24]
        reranker_spec = {"backend": self.settings.reranker_backend,
                         "model": self.settings.reranker_model,
                         "revision": self.settings.reranker_revision}
        if self.settings.reranker_backend == "lexical":
            reranker_spec = {"backend": "lexical", "model": "token-overlap", "revision": "1"}
        else:
            reranker_spec = self._pin_revision(reranker_spec, "reranking")
        manifest = {
            "schema_version": 1, "index_version": index_version,
            # Source document versions identify the corpus independently of
            # chunking/embedding, enabling controlled cross-config experiments.
            "corpus_snapshot_id": "corpus_" + _digest(corpus)[:20],
            "corpus_manifest_hash": _digest(corpus),
            "document_versions": [{"document_id": d, "document_version": v} for d, v in corpus],
            "embedding_spec": spec,
            "embedding_model_version": spec["backend"] + ":" + spec["model"] + "@" + str(spec["revision"] or "default") + ":" + _digest(spec)[:12],
            "chunking_config_id": configs[0] if len(configs) == 1 else "mixed_" + _digest(configs)[:16],
            "chunk_count": len(chunks), "chunks_sha256": _digest(chunks),
            "vector_dimension": int(vectors.shape[1]), "distance": "cosine",
            "bm25": {"tokenizer": "unicode-words-nfc-lower-v1", "k1": 1.5, "b": 0.75},
            "storage_backend": "qdrant" if getattr(self.settings, "qdrant_url", None) else "numpy",
            "collection": collection,
            "reranker_spec": reranker_spec,
            "demo_backends": spec["backend"] == "hash" or self.settings.reranker_backend == "lexical",
        }
        if manifest["storage_backend"] == "qdrant":
            # Persist resource identity before the first side effect, so a crash
            # during build can still be cleaned up without a published manifest.
            (directory / "resources.json").write_text(
                json.dumps({"storage_backend": "qdrant", "collection": collection}), encoding="utf-8")
            self._qdrant("PUT", f"/collections/{collection}",
                         {"vectors": {"size": int(vectors.shape[1]), "distance": "Cosine"}})
            try:
                for start in range(0, len(chunks), 64):
                    points = [{"id": c["chunk_id"], "vector": vectors[i].tolist(),
                               "payload": {"document_id": c["document_id"]}}
                              for i, c in enumerate(chunks[start:start + 64], start)]
                    self._qdrant("PUT", f"/collections/{collection}/points?wait=true", {"points": points})
                info = self._qdrant("GET", f"/collections/{collection}")["result"]
                if info["points_count"] != len(chunks):
                    raise ApiError(503, "DEPENDENCY_UNAVAILABLE", "Qdrant chưa lưu đủ chunk.", True)
            except Exception:
                self._qdrant("DELETE", f"/collections/{collection}")
                raise
        (directory / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
        np.save(directory / "vectors.npy", vectors, allow_pickle=False)
        manifest["vectors_sha256"] = hashlib.sha256((directory / "vectors.npy").read_bytes()).hexdigest()
        # Write manifest last; the caller publishes its active pointer separately.
        (directory / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    @staticmethod
    def _bm25(chunks, query_tokens):
        docs = [Counter(tokenize(c["text"])) for c in chunks]
        lengths = [sum(d.values()) for d in docs]
        average = sum(lengths) / max(1, len(docs)) or 1
        frequencies = Counter(term for d in docs for term in d)
        scores = []
        for terms, length in zip(docs, lengths):
            score = 0.0
            for term in set(query_tokens):
                frequency = terms.get(term, 0)
                if frequency:
                    idf = math.log(1 + (len(docs) - frequencies[term] + 0.5) / (frequencies[term] + 0.5))
                    score += idf * frequency * 2.5 / (frequency + 1.5 * (0.25 + 0.75 * length / average))
            scores.append(score)
        return scores

    def _rerank(self, query, chunks, spec):
        if spec["backend"] == "lexical":
            query_terms = set(tokenize(query))
            return [len(query_terms & set(tokenize(c["text"]))) / max(1, len(query_terms))
                    for c in chunks]
        if spec["backend"] != "cross_encoder":
            raise ApiError(503, "CONFIGURATION_MISSING", "Reranker backend không hợp lệ.")
        model = self._model(spec, "reranking")
        pairs = [(query, c["text"]) for c in chunks]
        try:
            raw_limit = getattr(model, "max_length", None) or model.tokenizer.model_max_length
            limit = min(raw_limit, 8192)  # Guard tokenizers advertising an unbounded sentinel.
            for q, passage in pairs:
                if len(model.tokenizer.encode(q, passage, truncation=False)) > limit:
                    raise ApiError(422, "MODEL_INPUT_TOO_LONG", "Query/chunk vượt giới hạn reranker.")
            return [float(x) for x in model.predict(pairs, show_progress_bar=False)]
        except ApiError:
            raise
        except Exception as exc:
            raise ApiError(503, "DEPENDENCY_UNAVAILABLE", "Reranker không thực hiện được yêu cầu.", True) from exc

    def search(self, directory: Path, query: str, config: dict,
               document_ids: list[str] | None = None) -> tuple[list[dict], dict]:
        directory = Path(directory)
        try:
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            chunks = json.loads((directory / "chunks.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ApiError(503, "DEPENDENCY_UNAVAILABLE", "Không đọc được snapshot retrieval.", True) from exc
        if _digest(chunks) != manifest["chunks_sha256"]:
            raise ApiError(503, "DEPENDENCY_UNAVAILABLE", "Snapshot retrieval không khớp manifest.")
        config = {"dense": True, "bm25": True, "reranking": True, "top_k": 5, **config}
        if not (config["dense"] or config["bm25"]) or not 1 <= config["top_k"] <= 20:
            raise ApiError(422, "VALIDATION_ERROR", "Cấu hình retrieval không hợp lệ.")
        allowed = set(document_ids) if document_ids is not None else None
        positions = [i for i, c in enumerate(chunks) if allowed is None or c["document_id"] in allowed]
        score_map = {i: {"dense": None, "bm25": None, "fusion": None, "rerank": None} for i in positions}
        rankings = []
        if config["dense"] and positions:
            vector = self._encode([query], manifest["embedding_spec"], query=True)[0]
            if manifest["storage_backend"] == "qdrant":
                body = {"query": vector.tolist(), "limit": 20, "with_payload": False}
                if allowed is not None:
                    body["filter"] = {"must": [{"key": "document_id", "match": {"any": list(allowed)}}]}
                response = self._qdrant("POST", f"/collections/{manifest['collection']}/points/query", body)
                lookup = {c["chunk_id"]: i for i, c in enumerate(chunks)}
                ranked = []
                for point in response["result"]["points"]:
                    i = lookup.get(str(point["id"]))
                    if i not in score_map:
                        raise ApiError(503, "DEPENDENCY_UNAVAILABLE", "Qdrant trả chunk ngoài snapshot.")
                    score_map[i]["dense"] = float(point["score"])
                    ranked.append(i)
            else:
                try:
                    vector_path = directory / "vectors.npy"
                    if hashlib.sha256(vector_path.read_bytes()).hexdigest() != manifest["vectors_sha256"]:
                        raise ValueError("vector checksum mismatch")
                    vectors = np.load(vector_path, allow_pickle=False)
                    if vectors.shape != (len(chunks), manifest["vector_dimension"]):
                        raise ValueError("vector shape mismatch")
                    scores = vectors @ vector
                except (ValueError, OSError) as exc:
                    raise ApiError(503, "DEPENDENCY_UNAVAILABLE", "Dense snapshot không hợp lệ.") from exc
                ranked = sorted(positions, key=lambda i: (-float(scores[i]), chunks[i]["chunk_id"]))[:20]
                for i in ranked:
                    score_map[i]["dense"] = float(scores[i])
            rankings.append(ranked)
        if config["bm25"] and positions:
            scores = self._bm25(chunks, tokenize(query))
            ranked = sorted((i for i in positions if scores[i] > 0),
                            key=lambda i: (-scores[i], chunks[i]["chunk_id"]))[:20]
            for i in ranked:
                score_map[i]["bm25"] = scores[i]
            rankings.append(ranked)
        fused = Counter()
        for ranking in rankings:
            for rank, i in enumerate(ranking, 1):
                fused[i] += 1 / (60 + rank)
        candidates = sorted(fused, key=lambda i: (-fused[i], chunks[i]["chunk_id"]))[:30]
        for i in candidates:
            score_map[i]["fusion"] = fused[i] if config["dense"] and config["bm25"] else None
        if config["reranking"] and candidates:
            values = self._rerank(query, [chunks[i] for i in candidates], manifest["reranker_spec"])
            for i, value in zip(candidates, values):
                score_map[i]["rerank"] = value
            ordered = sorted(candidates, key=lambda i: (-score_map[i]["rerank"], -fused[i], chunks[i]["chunk_id"]))
        else:
            ordered = candidates
        hits = []
        for rank, i in enumerate(ordered[:config["top_k"]], 1):
            chunk = chunks[i]
            hits.append({k: chunk[k] for k in ("chunk_id", "document_id", "document_version", "filename", "text", "source_spans")}
                        | {"rank": rank, "scores": score_map[i]})
        trace = {"resolved_index_version": manifest["index_version"],
                 "corpus_snapshot_id": manifest["corpus_snapshot_id"],
                 "embedding_model_version": manifest["embedding_model_version"],
                 "chunking_config_id": manifest["chunking_config_id"],
                 "effective_config": config, "candidate_count": len(candidates),
                 "reranked_count": len(candidates) if config["reranking"] else 0,
                 "returned_count": len(hits), "context_chunk_count": 0,
                 "retrieval_backend": manifest["embedding_spec"]["backend"],
                 "reranker_backend": manifest["reranker_spec"]["backend"],
                 "demo_backends": manifest["demo_backends"]}
        return hits, trace

    def delete(self, directory: Path) -> None:
        directory = Path(directory)
        manifest_file = directory / "manifest.json"
        if not manifest_file.exists():
            manifest_file = directory / "resources.json"
        if not manifest_file.exists():
            return
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
        if manifest["storage_backend"] == "qdrant":
            self._qdrant("DELETE", f"/collections/{manifest['collection']}")
