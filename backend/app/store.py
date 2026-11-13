"""Single-process SQLite registry and durable single-writer worker.

Run one uvicorn process: API writes revocations synchronously; the worker builds
immutable external artifacts, then publishes only after a registry epoch check.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import shutil
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from dataclasses import replace

from .chunking import chunk_pages
from .errors import ApiError
from .ingestion import PDF, extract, validate_file
from .retrieval import Engine

log = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat()


def uid(prefix):
    return f'{prefix}_{uuid.uuid4().hex}'


class Store:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.data_dir
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'documents').mkdir(exist_ok=True)
        (self.root / 'indexes').mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.engine = Engine(settings)
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        with self.db() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, hash TEXT, data TEXT);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, document_id TEXT, kind TEXT, status TEXT);
                CREATE TABLE IF NOT EXISTS generations(id TEXT PRIMARY KEY, status TEXT, members TEXT);
                CREATE TABLE IF NOT EXISTS tombstones(id TEXT PRIMARY KEY, completed INTEGER, deleted_at TEXT);
                CREATE TABLE IF NOT EXISTS idempotency(key TEXT PRIMARY KEY, fingerprint TEXT, document_id TEXT, created REAL);
                CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT);
                INSERT OR IGNORE INTO state VALUES('epoch', '0');
            ''')
        secret = self.root / 'cursor.key'
        if not secret.exists():
            secret.write_bytes(uuid.uuid4().bytes + uuid.uuid4().bytes)
        self.cursor_key = secret.read_bytes()

    @contextmanager
    def db(self):
        with self.lock:
            connection = sqlite3.connect(self.root / 'metadata.sqlite', timeout=30)
            connection.row_factory = sqlite3.Row
            try:
                with connection:
                    yield connection
            finally:
                connection.close()

    def docdir(self, ident):
        # ident always comes from the registry before use.
        return self.root / 'documents' / ident

    def _load(self, db, ident):
        row = db.execute('SELECT data FROM documents WHERE id=?', (ident,)).fetchone()
        if row:
            return json.loads(row['data'])
        if db.execute('SELECT 1 FROM tombstones WHERE id=?', (ident,)).fetchone():
            raise ApiError(410, 'DOCUMENT_DELETED', 'Tài liệu đã được xóa.')
        raise ApiError(404, 'DOCUMENT_NOT_FOUND', 'Không tìm thấy tài liệu.')

    def _save(self, db, document):
        document['updated_at'] = now()
        db.execute('UPDATE documents SET data=? WHERE id=?', (json.dumps(document, ensure_ascii=False), document['document_id']))

    def _versions(self, db, ident):
        return [row['id'] for row in db.execute("SELECT id,members FROM generations WHERE status='published'") if ident in json.loads(row['members'])]

    def public(self, db, document):
        result = {key: document[key] for key in ('document_id', 'document_version', 'filename', 'mime_type', 'size_bytes', 'status', 'page_count', 'job_id', 'error', 'created_at', 'updated_at')}
        result['available_index_versions'] = self._versions(db, document['document_id'])
        result['source_url'] = f"/api/v1/documents/{document['document_id']}/source?document_version=1" if document['page_count'] and document['status'] not in {'deleting', 'delete_failed'} else None
        return result

    def get(self, ident):
        with self.db() as db:
            return self.public(db, self._load(db, ident))

    def status(self, ident):
        with self.db() as db:
            document = self._load(db, ident)
            result = {key: document[key] for key in ('document_id', 'document_version', 'status', 'stage', 'progress', 'job_id', 'attempt', 'error', 'updated_at')}
            result['available_index_versions'] = self._versions(db, ident)
            return result

    def listing(self, limit, cursor, status):
        with self.db() as db:
            docs = [json.loads(row['data']) for row in db.execute('SELECT data FROM documents')]
            docs = sorted((d for d in docs if not status or d['status'] == status), key=lambda d: (d['created_at'], d['document_id']), reverse=True)
            if cursor:
                try:
                    raw = base64.urlsafe_b64decode(cursor.encode())
                    payload, signature = raw[:-32], raw[-32:]
                    if not hmac.compare_digest(signature, hmac.digest(self.cursor_key, payload, 'sha256')):
                        raise ValueError()
                    parsed = json.loads(payload)
                    if parsed['status'] != status:
                        raise ValueError()
                    docs = [d for d in docs if (d['created_at'], d['document_id']) < tuple(parsed['after'])]
                except Exception as exc:
                    raise ApiError(400, 'INVALID_CURSOR', 'Cursor không hợp lệ hoặc filter đã thay đổi.') from exc
            page = docs[:limit]
            next_cursor = None
            if len(docs) > limit:
                payload = json.dumps({'status': status, 'after': [page[-1]['created_at'], page[-1]['document_id']]}).encode()
                next_cursor = base64.urlsafe_b64encode(payload + hmac.digest(self.cursor_key, payload, 'sha256')).decode()
            return [self.public(db, d) for d in page], next_cursor

    def _key(self, db, key, fingerprint):
        db.execute('DELETE FROM idempotency WHERE created < ?', (time.time() - 86400,))
        record = db.execute('SELECT * FROM idempotency WHERE key=?', (key,)).fetchone()
        if record:
            if record['fingerprint'] != fingerprint:
                raise ApiError(409, 'IDEMPOTENCY_CONFLICT', 'Key đã được dùng cho nội dung khác.')
            document = self._load(db, record['document_id'])
            if document['status'] in {'deleting', 'delete_failed'}:
                raise ApiError(410, 'DOCUMENT_DELETING', 'Tài liệu đang bị xóa.')
            return document

    def upload(self, content, filename, mime, key):
        digest = hashlib.sha256(content).hexdigest()
        fingerprint = hashlib.sha256(('upload:' + digest + ':' + filename).encode()).hexdigest()
        with self.db() as db:
            replay = self._key(db, key, fingerprint)
            if replay:
                return self.public(db, replay), False
            row = db.execute('SELECT data FROM documents WHERE hash=?', (digest,)).fetchone()
            if row:
                doc = json.loads(row['data'])
                if doc['status'] in {'deleting', 'delete_failed'}:
                    raise ApiError(410, 'DOCUMENT_DELETING', 'Tài liệu đang bị xóa.')
                db.execute('INSERT INTO idempotency VALUES(?,?,?,?)', (key, fingerprint, doc['document_id'], time.time()))
                return self.public(db, doc), False
            ident, job = uid('doc'), uid('job')
            directory = self.docdir(ident)
            directory.mkdir()
            original = directory / ('original.pdf' if mime == PDF else 'original.docx')
            try:
                original.write_bytes(content)
                validate_file(original, mime)
            except Exception:
                shutil.rmtree(directory)
                raise
            doc = dict(document_id=ident, document_version=1, filename=filename, mime_type=mime,
                       size_bytes=len(content), status='queued', stage='queued', progress=0.0,
                       page_count=None, job_id=job, attempt=1, error=None, created_at=now(), updated_at=now())
            doc['ingestion_config'] = {key: getattr(self.settings, key) for key in (
                'embedding_backend', 'embedding_model', 'embedding_revision', 'reranker_backend',
                'reranker_model', 'reranker_revision', 'qdrant_url', 'chunking_strategy', 'chunk_size', 'chunk_overlap')}
            db.execute('INSERT INTO documents VALUES(?,?,?)', (ident, digest, json.dumps(doc, ensure_ascii=False)))
            db.execute('INSERT INTO jobs VALUES(?,?,?,?)', (job, ident, 'ingest', 'queued'))
            db.execute('INSERT INTO idempotency VALUES(?,?,?,?)', (key, fingerprint, ident, time.time()))
            result = self.public(db, doc)
        self.wake.set()
        return result, True

    def retry(self, ident, key):
        with self.db() as db:
            doc = self._key(db, key, 'retry:' + ident)
            if doc:
                return self.public(db, doc), False
            doc = self._load(db, ident)
            if doc['status'] in {'deleting', 'delete_failed'}:
                raise ApiError(410, 'DOCUMENT_DELETING', 'Tài liệu đang bị xóa.')
            if doc['status'] != 'failed':
                raise ApiError(409, 'INVALID_DOCUMENT_STATE', 'Chỉ retry tài liệu failed.')
            doc.update(status='queued', stage='queued', progress=0.0, error=None, attempt=doc['attempt'] + 1, job_id=uid('job'))
            self._save(db, doc)
            db.execute('INSERT INTO jobs VALUES(?,?,?,?)', (doc['job_id'], ident, 'ingest', 'queued'))
            db.execute('INSERT INTO idempotency VALUES(?,?,?,?)', (key, 'retry:' + ident, ident, time.time()))
            result = self.public(db, doc)
        self.wake.set()
        return result, True

    def delete(self, ident):
        with self.db() as db:
            tombstone = db.execute('SELECT completed FROM tombstones WHERE id=?', (ident,)).fetchone()
            if tombstone and tombstone['completed']:
                return None
            doc = self._load(db, ident)
            if doc['status'] != 'deleting':
                db.execute('INSERT OR IGNORE INTO tombstones VALUES(?,0,?)', (ident, now()))
                for row in db.execute("SELECT id,members FROM generations WHERE status IN ('published','building')").fetchall():
                    if ident in json.loads(row['members']):
                        db.execute("UPDATE generations SET status='revoked' WHERE id=?", (row['id'],))
                db.execute("UPDATE state SET value=CAST(value AS INTEGER)+1 WHERE key='epoch'")
                doc.update(status='deleting', stage='deleting', progress=None, error=None, job_id=uid('job'))
                self._save(db, doc)
                db.execute('INSERT INTO jobs VALUES(?,?,?,?)', (doc['job_id'], ident, 'delete', 'queued'))
            result = dict(document_id=ident, status='deleting', job_id=doc['job_id'])
        self.wake.set()
        return result

    def pin(self, version, ids):
        with self.db() as db:
            # Validate explicit scope first; never silently drop an invalid document.
            for ident in ids or []:
                doc = self._load(db, ident)
                if doc['status'] in {'deleting', 'delete_failed'}:
                    raise ApiError(410, 'DOCUMENT_DELETING', 'Tài liệu đã bị thu hồi.')
            if version is None:
                row = db.execute("SELECT value FROM state WHERE key='active'").fetchone()
                version = row['value'] if row else None
                row = db.execute('SELECT * FROM generations WHERE id=?', (version,)).fetchone()
                if not row or row['status'] != 'published':
                    raise ApiError(503, 'INDEX_NOT_READY', 'Index chưa sẵn sàng.', True)
            else:
                row = db.execute('SELECT * FROM generations WHERE id=?', (version,)).fetchone()
                if not row:
                    raise ApiError(404, 'INDEX_VERSION_NOT_FOUND', 'Không tìm thấy phiên bản index.')
                if row['status'] != 'published':
                    raise ApiError(409, 'INDEX_VERSION_UNAVAILABLE', 'Phiên bản index không thể phục vụ.')
            members = json.loads(row['members'])
            if any(ident not in members for ident in ids or []):
                raise ApiError(409, 'DOCUMENT_NOT_INDEXED', 'Tài liệu chưa có trong phiên bản index này.')
            return version, self.root / 'indexes' / version

    def recheck(self, version):
        with self.db() as db:
            row = db.execute('SELECT status FROM generations WHERE id=?', (version,)).fetchone()
            if not row or row['status'] != 'published':
                raise ApiError(409, 'SOURCE_SET_CHANGED', 'Nguồn đã bị thu hồi trong lúc xử lý.', True)

    def source(self, ident, version):
        with self.db() as db:
            doc = self._load(db, ident)
            if doc['status'] in {'deleting', 'delete_failed'}:
                raise ApiError(410, 'DOCUMENT_DELETING', 'Nguồn đã bị thu hồi.')
            if version != doc['document_version']:
                raise ApiError(404, 'DOCUMENT_VERSION_NOT_FOUND', 'Không tìm thấy phiên bản tài liệu.')
            path = self.docdir(ident) / 'source.pdf'
            if not path.exists():
                raise ApiError(409, 'SOURCE_NOT_READY', 'Bản PDF chuẩn chưa sẵn sàng.', True)
            return path.read_bytes()

    def acquire_lease(self):
        self.lease = (self.root / 'writer.lock').open('a+b')
        self.lease.write(b'0')
        self.lease.flush()
        self.lease.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.lease.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lease.close()
            raise RuntimeError('DATA_DIR đã được một server sử dụng. Chạy đúng một worker.') from None

    def start(self):
        self.acquire_lease()
        with self.db() as db:
            db.execute("UPDATE jobs SET status='queued' WHERE status='running'")
            db.execute("UPDATE generations SET status='failed' WHERE status='building'")
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._loop, daemon=True, name='ingestion-worker')
        self.thread.start()

    def close(self):
        self.stop_event.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=5)
        if not self.thread or not self.thread.is_alive():
            self.lease.close()

    def _progress(self, ident, **changes):
        with self.db() as db:
            doc = self._load(db, ident)
            if doc['status'] in {'deleting', 'delete_failed'}:
                raise ApiError(410, 'DOCUMENT_DELETING', 'Tài liệu đang bị xóa.')
            doc.update(changes)
            self._save(db, doc)

    def _publish(self, extra=None):
        for _ in range(4):
            with self.db() as db:
                build_settings = self.settings
                if extra:
                    source = self._load(db, extra)
                    if source['status'] != 'processing' or db.execute('SELECT 1 FROM tombstones WHERE id=?', (extra,)).fetchone():
                        raise ApiError(410, 'DOCUMENT_DELETING', 'Tài liệu đã bị thu hồi.')
                    build_settings = replace(self.settings, **source['ingestion_config'])
                epoch = db.execute("SELECT value FROM state WHERE key='epoch'").fetchone()['value']
                docs = [json.loads(r['data']) for r in db.execute('SELECT data FROM documents')]
                docs = [d for d in docs if d['status'] == 'ready' or (d['document_id'] == extra and d['status'] == 'processing')]
                members = {d['document_id']: d['document_version'] for d in docs}
                if not members:
                    db.execute("DELETE FROM state WHERE key='active'")
                    return
                version = uid('idx')
                db.execute('INSERT INTO generations VALUES(?,?,?)', (version, 'building', json.dumps(members)))
            path = self.root / 'indexes' / version
            engine = Engine(build_settings)
            try:
                chunks = []
                for doc in docs:
                    pages = json.loads((self.docdir(doc['document_id']) / 'pages.json').read_text(encoding='utf-8'))
                    chunks.extend(chunk_pages(doc, pages, strategy=build_settings.chunking_strategy, size=build_settings.chunk_size, overlap=build_settings.chunk_overlap))
                engine.build(version, chunks, path)
                with self.db() as db:
                    current = db.execute("SELECT value FROM state WHERE key='epoch'").fetchone()['value']
                    if current == epoch:
                        if extra:
                            source = self._load(db, extra)
                            if source['status'] != 'processing' or db.execute('SELECT 1 FROM tombstones WHERE id=?', (extra,)).fetchone():
                                raise ApiError(410, 'DOCUMENT_DELETING', 'Tài liệu đã bị thu hồi.')
                        db.execute("UPDATE generations SET status='published' WHERE id=?", (version,))
                        db.execute("INSERT OR REPLACE INTO state VALUES('active',?)", (version,))
                        if extra:
                            doc = self._load(db, extra)
                            doc.update(status='ready', stage='completed', progress=1.0, error=None)
                            self._save(db, doc)
                        return
                    db.execute("UPDATE generations SET status='revoked' WHERE id=?", (version,))
                engine.delete(path)
                shutil.rmtree(path, ignore_errors=True)
            except Exception:
                with self.db() as db:
                    db.execute("UPDATE generations SET status='failed' WHERE id=? AND status='building'", (version,))
                # Retain failed artifacts only when cleanup itself fails, so DELETE
                # can find and retry them from the persisted generation registry.
                if path.exists():
                    try:
                        engine.delete(path)
                        shutil.rmtree(path)
                    except Exception:
                        log.exception('Staging cleanup needs retry: %s', version)
                raise
        raise ApiError(503, 'SOURCE_SET_CHANGED', 'Corpus thay đổi liên tục; hãy retry.', True)

    def _ingest(self, ident):
        self._progress(ident, status='processing', stage='extracting', progress=None)
        with self.db() as db:
            doc = self._load(db, ident)
        pages = extract(self.docdir(ident), doc['mime_type'], self.settings)
        self._progress(ident, page_count=len(pages), stage='indexing')
        (self.docdir(ident) / 'pages.json').write_text(json.dumps(pages, ensure_ascii=False), encoding='utf-8')
        self._publish(extra=ident)

    def _cleanup(self, ident):
        with self.db() as db:
            generations = [row['id'] for row in db.execute('SELECT id,members FROM generations') if ident in json.loads(row['members'])]
        for version in generations:
            path = self.root / 'indexes' / version
            if path.exists():
                self.engine.delete(path)
                shutil.rmtree(path)
        directory = self.docdir(ident)
        if directory.exists():
            shutil.rmtree(directory)
        # Publish successor before purging the job's registry. Failure remains retryable.
        self._publish()
        with self.db() as db:
            db.execute('DELETE FROM documents WHERE id=?', (ident,))
            db.execute('UPDATE tombstones SET completed=1 WHERE id=?', (ident,))

    def _loop(self):
        with self.db() as db:
            abandoned = [r['id'] for r in db.execute("SELECT id FROM generations WHERE status='failed'")]
        for version in abandoned:
            path = self.root / 'indexes' / version
            if path.exists():
                try:
                    self.engine.delete(path)
                    shutil.rmtree(path)
                except Exception:
                    log.exception('Abandoned staging cleanup failed: %s', version)
        while not self.stop_event.is_set():
            with self.db() as db:
                job = db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
                if job:
                    job = dict(job)
                    db.execute("UPDATE jobs SET status='running' WHERE id=?", (job['id'],))
            if not job:
                self.wake.wait(.25)
                self.wake.clear()
                continue
            try:
                if job['kind'] == 'ingest':
                    self._ingest(job['document_id'])
                else:
                    self._cleanup(job['document_id'])
                outcome = 'completed'
            except Exception as exc:
                log.exception('Worker job failed: %s', job['id'])
                error = exc if isinstance(exc, ApiError) else ApiError(500, 'PROCESSING_FAILED', 'Xử lý thất bại; xem log server.', True)
                with self.db() as db:
                    row = db.execute('SELECT data FROM documents WHERE id=?', (job['document_id'],)).fetchone()
                    if row:
                        doc = json.loads(row['data'])
                        if job['kind'] == 'delete' or doc['status'] not in {'deleting', 'delete_failed'}:
                            doc.update(status='delete_failed' if job['kind'] == 'delete' else 'failed', stage='failed', progress=None, error=error.payload())
                            self._save(db, doc)
                outcome = 'failed'
            with self.db() as db:
                db.execute('UPDATE jobs SET status=? WHERE id=?', (outcome, job['id']))
