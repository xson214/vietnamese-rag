export type DocumentStatus = 'queued' | 'processing' | 'ready' | 'failed' | 'deleting' | 'delete_failed'
export type Document = {document_id: string; document_version: number; filename: string; mime_type: string; size_bytes: number; status: DocumentStatus; page_count: number | null; available_index_versions: string[]; source_url: string | null; error: {code: string; message: string} | null}
export type RetrievalConfig = {dense: boolean; bm25: boolean; reranking: boolean; top_k: number}
export type GenerationConfig = {backend: 'extractive' | 'api'; base_url: string; model: string; api_key: string}
export type Citation = {source_id: string; document_id: string; document_version: number; filename: string; page_number: number; quote: string; source_url: string}
export type Trace = {resolved_index_version: string; corpus_snapshot_id: string; embedding_model_version: string; chunking_config_id: string; candidate_count: number; reranked_count: number; returned_count: number; context_chunk_count: number; effective_config: RetrievalConfig; generation_backend?: string; llm_model?: string | null}
export type Answer = {request_id: string; status: 'answered' | 'insufficient_evidence'; answer: string; citations: Citation[]; confidence: {level: string; score: number | null} | null; retrieval_trace: Trace}
export type Health = {status: 'ok' | 'degraded' | 'unavailable'; active_index_version: string | null; components: Record<string, string>; modes?: {embedding?: string; reranker?: string; generation?: string}}
export class ApiError extends Error {
  status: number
  code: string
  requestId?: string
  constructor(status: number, message: string, code = 'NETWORK_ERROR', requestId?: string) {
    super(message); this.status = status; this.code = code; this.requestId = requestId
  }
}
export async function request<T>(url: string, options?: RequestInit): Promise<T> {
  let response: Response
  try {response = await fetch(`/api/v1${url}`, options)} catch {throw new ApiError(0, 'Không kết nối được máy chủ. Hãy kiểm tra backend và thử lại.')}
  if (response.status === 204) return undefined as T
  let body: unknown
  try {body = await response.json()} catch {throw new ApiError(response.status, 'Máy chủ trả về dữ liệu không hợp lệ.', 'INVALID_RESPONSE', response.headers.get('X-Request-ID') ?? undefined)}
  if (!response.ok) {
    const failure = body as {error?: {message?: string; code?: string}; request_id?: string}
    throw new ApiError(response.status, failure.error?.message ?? 'Dịch vụ hiện chưa sẵn sàng.', failure.error?.code ?? 'SERVICE_UNAVAILABLE', failure.request_id)
  }
  return body as T
}
export async function getHealth(): Promise<Health> {
  try {
    const response = await fetch('/api/v1/health')
    const body = await response.json() as Health
    if (!body.components) throw new Error('Invalid health')
    return body
  } catch {return {status: 'unavailable', active_index_version: null, components: {}}}
}
export async function getDocuments(): Promise<Document[]> {
  const all: Document[] = []
  let cursor: string | null = null
  do {
    const page: {items: Document[]; next_cursor: string | null} = await request(`/documents?limit=100${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ''}`)
    all.push(...page.items); cursor = page.next_cursor
  } while (cursor)
  return all
}
export function safeSource(url: string | null, page = 1): string | undefined {
  if (!url || !/^\/api\/v1\/documents\/[a-zA-Z0-9_-]+\/source\?document_version=\d+$/.test(url)) return undefined
  return `${url}#page=${Math.max(1, Math.floor(page))}`
}
export function idempotencyKey(): string {return crypto.randomUUID()}
