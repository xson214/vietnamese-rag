import logging
import re
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .errors import ApiError
from .generation import Generator
from .ingestion import DOCX, PDF, JPEG, PNG, WEBP
from .model_settings import fetch_models, resolve_generation_settings
from .schemas import (ChatRequest, ChatResponse, DeleteResponse, DocumentListResponse,
                      DocumentResponse, ErrorResponse, HealthResponse, SearchRequest,
                      SearchResponse, StatusResponse, ModelsRequest, ModelsResponse)
from .store import Store, now, uid

log = logging.getLogger(__name__)
ERRORS = {str(code): {'model': ErrorResponse} for code in (400,404,409,410,413,415,422,429,500,502,503,504)}


def create_app(settings=None):
    settings = settings or Settings()
    store = Store(settings)
    generator = Generator(settings)

    @asynccontextmanager
    async def lifespan(app):
        store.start()
        yield
        store.close()

    app = FastAPI(title='Vietnamese RAG', version='0.1.0', lifespan=lifespan,
                  description='Local document Q&A. Demo backends are explicitly labelled in health and retrieval trace.')
    app.state.store = store
    app.state.generator = generator

    @app.middleware('http')
    async def request_id(request, call_next):
        request.state.request_id = uid('req')
        try:
            response = await call_next(request)
        except Exception:
            log.exception('Unhandled request: %s', request.state.request_id)
            response = JSONResponse({'request_id': request.state.request_id, 'status': 'error',
                'error': ApiError(500, 'INTERNAL_ERROR', 'Lỗi hệ thống.').payload()}, status_code=500)
        response.headers['X-Request-ID'] = request.state.request_id
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.exception_handler(ApiError)
    async def api_error(request, exc):
        return JSONResponse({'request_id': request.state.request_id, 'status': 'error', 'error': exc.payload()}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        details = [{'field': '.'.join(map(str, e['loc'])), 'reason': e['msg']} for e in exc.errors()]
        malformed = any(e['type'] == 'json_invalid' for e in exc.errors())
        error = ApiError(400 if malformed else 422, 'MALFORMED_REQUEST' if malformed else 'VALIDATION_ERROR', 'Request không hợp lệ.', details=details)
        return JSONResponse({'request_id': request.state.request_id, 'status': 'error', 'error': error.payload()}, status_code=error.status)

    def body(request, **fields):
        return {'request_id': request.state.request_id, **fields}

    def idempotency(key):
        if not key or not key.strip() or len(key) > 200:
            raise ApiError(422, 'VALIDATION_ERROR', 'Idempotency-Key phải có 1–200 ký tự.')
        return key

    @app.post('/api/v1/documents', response_model=DocumentResponse, status_code=202, responses={**ERRORS, '200': {'model': DocumentResponse}}, tags=['documents'])
    async def upload(request: Request, response: Response, idempotency_key: Annotated[str, Header()]):
        key = idempotency(idempotency_key)
        if not request.headers.get('content-type', '').startswith('multipart/form-data'):
            raise ApiError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Upload cần multipart/form-data.')
        # Limit body before multipart parsing, including clients without Content-Length.
        total, buffers = 0, []
        async for chunk in request.stream():
            total += len(chunk)
            if total > settings.max_file_bytes + 65536:
                raise ApiError(413, 'FILE_TOO_LARGE', 'File vượt giới hạn 20 MiB.')
            buffers.append(chunk)
        request._body = b''.join(buffers)
        try:
            form = await request.form(max_files=1, max_fields=0, max_part_size=settings.max_file_bytes)
        except Exception as exc:
            raise ApiError(400, 'MALFORMED_REQUEST', 'Multipart không hợp lệ hoặc có quá nhiều trường.') from exc
        try:
            items = form.multi_items()
            if len(items) != 1 or items[0][0] != 'file' or not hasattr(items[0][1], 'read'):
                raise ApiError(422, 'VALIDATION_ERROR', 'Gửi đúng một trường file.')
            file = items[0][1]
            content = await file.read(settings.max_file_bytes + 1)
            if len(content) > settings.max_file_bytes:
                raise ApiError(413, 'FILE_TOO_LARGE', 'File vượt giới hạn 20 MiB.')
            if not content:
                raise ApiError(422, 'INVALID_DOCUMENT', 'File không có nội dung.')
            filename = re.sub(r'[\x00-\x1f\x7f]', '', (file.filename or 'document').replace('\\', '/').split('/')[-1])[:200] or 'document'
            suffix = filename.rsplit('.', 1)[-1].lower()
            mime = {'pdf': PDF, 'docx': DOCX, 'jpg':JPEG, 'jpeg':JPEG, 'png':PNG, 'webp':WEBP}.get(suffix)
            if mime is None or file.content_type not in {mime, 'application/octet-stream'}:
                raise ApiError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Chỉ hỗ trợ PDF, DOCX, JPG, PNG hoặc WebP đúng MIME.')
            document, created = await run_in_threadpool(store.upload, content, filename, mime, key)
        finally:
            await form.close()
        response.status_code = 202 if created else 200
        response.headers['Location'] = f"/api/v1/documents/{document['document_id']}"
        response.headers['Retry-After'] = '2'
        return body(request, document=document)

    @app.get('/api/v1/documents', response_model=DocumentListResponse, responses=ERRORS, tags=['documents'])
    def documents(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 20, cursor: str | None = None,
                  status: Literal['queued','processing','ready','failed','deleting','delete_failed'] | None = None):
        items, next_cursor = store.listing(limit, cursor, status)
        return body(request, items=items, next_cursor=next_cursor)

    @app.get('/api/v1/documents/{id}', response_model=DocumentResponse, responses=ERRORS, tags=['documents'])
    def detail(id: str, request: Request):
        return body(request, document=store.get(id))

    @app.get('/api/v1/documents/{id}/status', response_model=StatusResponse, responses=ERRORS, tags=['documents'])
    def status(id: str, request: Request):
        return body(request, **store.status(id))

    @app.post('/api/v1/documents/{id}/retry', response_model=DocumentResponse, status_code=202, responses={**ERRORS, '200': {'model': DocumentResponse}}, tags=['documents'])
    async def retry(id: str, request: Request, response: Response, idempotency_key: Annotated[str, Header()]):
        if await request.body():
            raise ApiError(422, 'VALIDATION_ERROR', 'Retry không nhận body.')
        document, created = store.retry(id, idempotency(idempotency_key))
        response.status_code = 202 if created else 200
        response.headers['Retry-After'] = '2'
        return body(request, document=document)

    @app.post('/api/v1/documents/{id}/reprocess', response_model=DocumentResponse, status_code=202, responses={**ERRORS, '200': {'model': DocumentResponse}}, tags=['documents'])
    async def reprocess(id: str, request: Request, response: Response, idempotency_key: Annotated[str, Header()]):
        if await request.body():
            raise ApiError(422, 'VALIDATION_ERROR', 'Đọc lại tài liệu không nhận body.')
        document, created = await run_in_threadpool(store.reprocess, id, idempotency(idempotency_key))
        response.status_code = 202 if created else 200
        response.headers['Retry-After'] = '2'
        response.headers['Location'] = f"/api/v1/documents/{id}"
        return body(request, document=document)

    @app.delete('/api/v1/documents/{id}', response_model=DeleteResponse, status_code=202, responses={**ERRORS, '204': {'description': 'Đã xóa nội dung khỏi mọi store.'}}, tags=['documents'])
    def delete(id: str, request: Request):
        result = store.delete(id)
        if result is None:
            return Response(status_code=204)
        return JSONResponse(body(request, **result), status_code=202, headers={'Retry-After': '2'})

    @app.get('/api/v1/documents/{id}/source', responses={**ERRORS, '200': {'content': {'application/pdf': {}}}}, response_class=Response, tags=['documents'])
    def source(id: str, document_version: Annotated[int, Query(ge=1)]):
        return Response(store.source(id, document_version), media_type='application/pdf', headers={'Content-Disposition': 'inline; filename="source.pdf"'})

    def retrieve(payload, query):
        version, directory = store.pin(payload.index_version, payload.document_ids)
        try:
            hits, trace = store.engine.search(directory, query, payload.retrieval_config.model_dump(), payload.document_ids)
            hits = store.attach_extraction(hits)
        except Exception:
            store.recheck(version)
            raise
        store.recheck(version)
        return version, hits, trace

    @app.post('/api/v1/search', response_model=SearchResponse, responses=ERRORS, tags=['retrieval'])
    def search(payload: SearchRequest, request: Request):
        _, hits, trace = retrieve(payload, payload.query)
        return body(request, hits=hits, retrieval_trace=trace)

    @app.post('/api/v1/chat', response_model=ChatResponse, responses=ERRORS, tags=['chat'])
    def chat(payload: ChatRequest, request: Request):
        resolved = resolve_generation_settings(settings, payload.generation_config)
        version, hits, trace = retrieve(payload, payload.question)
        selected = Generator(resolved) if payload.generation_config is not None else generator
        result = selected.answer(payload.question, hits, trace)
        store.recheck(version)
        return body(request, **result)

    @app.post('/api/v1/models', response_model=ModelsResponse, responses=ERRORS, tags=['settings'])
    def models(payload: ModelsRequest, request: Request):
        return body(request, models=fetch_models(payload))

    @app.get('/api/v1/health', response_model=HealthResponse, responses={'503': {'model': HealthResponse}}, tags=['system'])
    def health(request: Request, response: Response):
        components = dict(sqlite='ok', file_storage='ok', worker='ok' if store.thread and store.thread.is_alive() else 'unavailable', dense='unavailable', bm25='unavailable', llm='configured')
        active = None
        try:
            active, _ = store.pin(None, None)
            components.update(dense='ok', bm25='ok')
        except ApiError:
            pass
        if settings.generation_backend == 'api' and not (settings.llm_base_url and settings.llm_model):
            components['llm'] = 'not_configured'
        ready = active is not None and components['worker'] == 'ok' and components['llm'] == 'configured'
        response.status_code = 200 if ready else 503
        return body(request, status='ok' if ready else 'unavailable', checked_at=now(), active_index_version=active, components=components,
                    modes={'embedding': settings.embedding_backend, 'reranker': settings.reranker_backend, 'generation': settings.generation_backend})

    original_openapi = app.openapi

    def openapi():
        schema = original_openapi()
        schema['paths']['/api/v1/documents']['post']['requestBody'] = {
            'required':True, 'content': {'multipart/form-data': {'schema': {
                'type':'object','required':['file'],'additionalProperties':False,
                'properties': {'file': {'type':'string','format':'binary'}}}}}}
        for path in schema['paths'].values():
            for operation in path.values():
                for response in operation.get('responses', {}).values():
                    response.setdefault('headers', {})['X-Request-ID'] = {
                        'description':'Server-generated request ID','schema':{'type':'string'}}
        return schema

    app.openapi = openapi
    return app


app = create_app()
