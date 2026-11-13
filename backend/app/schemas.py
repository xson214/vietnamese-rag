from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class RetrievalConfig(StrictModel):
    model_config = ConfigDict(extra='forbid', strict=True, json_schema_extra={
        'not': {'properties': {'dense': {'const': False}, 'bm25': {'const': False}}, 'required':['dense','bm25']}
    })
    dense: bool = True
    bm25: bool = True
    reranking: bool = True
    top_k: int = Field(default=5, ge=1, le=20)

    @model_validator(mode='after')
    def enabled(self):
        if not self.dense and not self.bm25:
            raise ValueError('Phải bật dense hoặc bm25.')
        return self


def scope_schema(schema):
    for field in ('document_ids', 'index_version'):
        prop = schema['properties'][field]
        prop.update(prop.pop('anyOf')[0])
        prop.pop('default', None)
    schema['properties']['document_ids']['uniqueItems'] = True


class ScopedRequest(StrictModel):
    model_config = ConfigDict(extra='forbid', strict=True, json_schema_extra=scope_schema)
    document_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)
    index_version: str | None = Field(default=None, min_length=1, max_length=200)
    retrieval_config: RetrievalConfig = Field(default_factory=RetrievalConfig)

    @field_validator('document_ids', 'index_version', mode='before')
    @classmethod
    def no_explicit_null(cls, value):
        if value is None:
            raise ValueError('Bỏ qua trường nếu không chọn phạm vi/phiên bản; không gửi null.')
        return value

    @field_validator('document_ids')
    @classmethod
    def unique_ids(cls, value):
        if value is not None and (len(value) != len(set(value)) or any(not i.strip() for i in value)):
            raise ValueError('document_ids phải chứa ID duy nhất, không rỗng.')
        return value


class SearchRequest(ScopedRequest):
    query: str = Field(min_length=1, max_length=4000)

    @field_validator('query', mode='before')
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class ChatRequest(ScopedRequest):
    question: str = Field(min_length=1, max_length=4000)

    @field_validator('question', mode='before')
    @classmethod
    def trim(cls, value):
        return value.strip() if isinstance(value, str) else value


class ErrorDetail(BaseModel):
    field: str
    reason: str


class ErrorInfo(BaseModel):
    code: str
    message: str
    retryable: bool
    details: list[ErrorDetail] = []


class ErrorResponse(BaseModel):
    request_id: str
    status: Literal['error'] = 'error'
    error: ErrorInfo


class Document(BaseModel):
    document_id: str
    document_version: int
    filename: str
    mime_type: str
    size_bytes: int
    status: Literal['queued', 'processing', 'ready', 'failed', 'deleting', 'delete_failed']
    page_count: int | None
    job_id: str | None
    available_index_versions: list[str]
    source_url: str | None
    error: ErrorInfo | None
    created_at: str
    updated_at: str


class DocumentResponse(BaseModel):
    request_id: str
    document: Document


class DocumentListResponse(BaseModel):
    request_id: str
    items: list[Document]
    next_cursor: str | None


class StatusResponse(BaseModel):
    request_id: str
    document_id: str
    document_version: int
    status: str
    stage: str
    progress: float | None
    job_id: str | None
    attempt: int
    available_index_versions: list[str]
    error: ErrorInfo | None
    updated_at: str


class DeleteResponse(BaseModel):
    request_id: str
    document_id: str
    status: Literal['deleting']
    job_id: str


class SourceSpan(BaseModel):
    page_number: int = Field(ge=1)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=1)
    quote: str


class Scores(BaseModel):
    dense: float | None = None
    bm25: float | None = None
    fusion: float | None = None
    rerank: float | None = None


class SearchHit(BaseModel):
    chunk_id: str
    document_id: str
    document_version: int
    filename: str
    text: str
    source_spans: list[SourceSpan]
    rank: int
    scores: Scores


class RetrievalTrace(BaseModel):
    model_config = ConfigDict(extra='allow')
    resolved_index_version: str
    corpus_snapshot_id: str
    embedding_model_version: str
    chunking_config_id: str
    effective_config: RetrievalConfig
    candidate_count: int
    reranked_count: int
    returned_count: int
    context_chunk_count: int


class SearchResponse(BaseModel):
    request_id: str
    hits: list[SearchHit]
    retrieval_trace: RetrievalTrace


class CitationOffset(BaseModel):
    start_offset: int
    end_offset: int


class Citation(BaseModel):
    source_id: str
    document_id: str
    document_version: int
    filename: str
    page_number: int
    quote: str
    source_span: CitationOffset
    source_url: str


class ChatResponse(BaseModel):
    model_config = ConfigDict(json_schema_extra={'allOf': [
        {'if': {'properties': {'status': {'const':'answered'}}},
         'then': {'properties': {'citations': {'minItems':1}}},
         'else': {'properties': {'citations': {'maxItems':0}}}}
    ]})
    request_id: str
    status: Literal['answered', 'insufficient_evidence']
    answer: str
    citations: list[Citation]
    confidence: None = None
    retrieval_trace: RetrievalTrace

    @model_validator(mode='after')
    def citation_rules(self):
        if (self.status == 'answered') != bool(self.citations):
            raise ValueError('answered requires citations; insufficient_evidence forbids citations')
        return self


class HealthResponse(BaseModel):
    request_id: str
    status: Literal['ok', 'degraded', 'unavailable']
    checked_at: str
    active_index_version: str | None
    components: dict[str, str]
    modes: dict[str, str]
