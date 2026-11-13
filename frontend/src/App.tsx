import {useCallback, useEffect, useRef, useState} from 'react'
import type {ChangeEvent, FormEvent, ReactNode} from 'react'
import {ApiError, getDocuments, getHealth, idempotencyKey, request, safeSource} from './api'
import type {Answer, Citation, Document, GenerationConfig, Health, RetrievalConfig} from './api'
import ModelSettings from './ModelSettings'

type IconName = 'book' | 'upload' | 'arrow' | 'plus' | 'file' | 'search' | 'settings' | 'external' | 'trash' | 'refresh' | 'check' | 'close' | 'shield'
const paths: Record<IconName, ReactNode> = {
  book: <><path d="M3 4h6a4 4 0 0 1 3 2 4 4 0 0 1 3-2h6v15h-6a4 4 0 0 0-3 2 4 4 0 0 0-3-2H3Z"/><path d="M12 6v15"/></>,
  upload: <><path d="m7 8 5-5 5 5M12 3v12M4 15v6h16v-6"/></>,
  arrow: <><path d="m12 19 0-14m-6 6 6-6 6 6"/></>,
  plus: <path d="M12 5v14M5 12h14"/>, file: <><path d="M14 3H5v18h14V8ZM14 3v6h5M8 13h8M8 17h6"/></>,
  search: <><circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/></>,
  settings: <><path d="M4 6h16M4 12h16M4 18h16"/><path d="M8 3v6m8 0v6M9 15v6"/></>,
  external: <><path d="M14 3h7v7m0-7L10 14M10 4H4v16h16v-6"/></>,
  trash: <><path d="M3 6h18M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7m4-7v7"/></>,
  refresh: <><path d="M20 7v5h-5M4 17v-5h5M6 6a8 8 0 0 1 14 6M4 12a8 8 0 0 0 14 6"/></>,
  check: <path d="m5 12 4 4L19 6"/>, close: <path d="m6 6 12 12M6 18 18 6"/>,
  shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Z"/><path d="m8 12 3 3 5-6"/></>,
}
function Icon({name, size = 20}: {name: IconName; size?: number}) {return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>}
const statusNames = {queued: 'Đang chờ', processing: 'Đang xử lý', ready: 'Sẵn sàng', failed: 'Xử lý thất bại', deleting: 'Đang xóa', delete_failed: 'Xóa chưa hoàn tất'}
type Turn = {id: string; question: string; result?: Answer; error?: ApiError}
const suggestions = ['Tài liệu trình bày những nội dung chính nào?', 'Các nguyên tắc hoạt động của hệ thống là gì?', 'Điều kiện và quy trình thực hiện là gì?']
function errorOf(error: unknown) {return error instanceof ApiError ? error : new ApiError(0, error instanceof Error ? error.message : 'Đã có lỗi xảy ra.')}

export default function App() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [scopeAll, setScopeAll] = useState(true)
  const [query, setQuery] = useState('')
  const [config, setConfig] = useState<RetrievalConfig>({dense: true, bm25: true, reranking: true, top_k: 5})
  const [generationConfig, setGenerationConfig] = useState<GenerationConfig | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [dragging, setDragging] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<ApiError | null>(null)
  const [notice, setNotice] = useState('')
  const [deleteTarget, setDeleteTarget] = useState<Document | null>(null)
  const [actionId, setActionId] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [docFilter, setDocFilter] = useState('')
  const [activeSource, setActiveSource] = useState<Citation | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const textarea = useRef<HTMLTextAreaElement>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const refresh = useCallback(async () => {
    try {
      const docs = await getDocuments(); setDocuments(docs)
      setSelected(ids => ids.filter(id => docs.some(doc => doc.document_id === id && doc.status === 'ready' && doc.available_index_versions.length > 0)))
    } catch (e) {setError(errorOf(e))} finally {setLoading(false)}
  }, [])
  useEffect(() => {void refresh(); void getHealth().then(setHealth); const id = setInterval(() => {void getHealth().then(setHealth)}, 10000); return () => clearInterval(id)}, [refresh])
  const pending = documents.some(doc => ['queued', 'processing', 'deleting'].includes(doc.status))
  useEffect(() => {if (!pending) return; const id = setInterval(() => {void refresh()}, 2000); return () => clearInterval(id)}, [pending, refresh])
  useEffect(() => {bottom.current?.scrollIntoView({behavior: 'smooth', block: 'end'})}, [turns, busy])
  useEffect(() => {if (!notice) return; const id = setTimeout(() => setNotice(''), 6000); return () => clearTimeout(id)}, [notice])
  useEffect(() => {const close = (event: KeyboardEvent) => {if (event.key === 'Escape') {setDeleteTarget(null); setActiveSource(null)}}; document.addEventListener('keydown', close); return () => document.removeEventListener('keydown', close)}, [])
  const ready = documents.filter(doc => doc.status === 'ready' && doc.available_index_versions.length > 0)
  const scopeReady = scopeAll ? ready.length > 0 : selected.length > 0
  const canAsk = scopeReady && !busy && !!query.trim() && (config.dense || config.bm25)
  const filteredDocuments = documents.filter(doc => doc.filename.toLocaleLowerCase('vi').includes(docFilter.toLocaleLowerCase('vi')))

  async function upload(files: FileList | File[] | null) {
    if (!files?.length || uploading) return
    setError(null); setUploading(true)
    let successes = 0
    try {
      for (const file of Array.from(files)) {
        if (!/\.(pdf|docx)$/i.test(file.name)) throw new ApiError(415, 'Chỉ nhận tài liệu PDF hoặc DOCX.')
        if (file.size > 20 * 1024 * 1024) throw new ApiError(413, `${file.name}: vượt giới hạn 20 MB.`)
        const form = new FormData(); form.append('file', file)
        await request('/documents', {method: 'POST', headers: {'Idempotency-Key': idempotencyKey()}, body: form}); successes++
      }
      setNotice(`Đã tiếp nhận ${successes} tài liệu. Hệ thống đang chuẩn bị dữ liệu để tìm kiếm.`)
    } catch (e) {setError(errorOf(e))} finally {setUploading(false); await refresh(); void getHealth().then(setHealth); if (fileInput.current) fileInput.current.value = ''}
  }
  async function retry(doc: Document) {
    setActionId(doc.document_id); setError(null)
    try {await request(`/documents/${encodeURIComponent(doc.document_id)}/retry`, {method: 'POST', headers: {'Idempotency-Key': idempotencyKey()}}); await refresh()} catch (e) {setError(errorOf(e))} finally {setActionId(null)}
  }
  async function remove() {
    if (!deleteTarget) return
    const target = deleteTarget; setDeleteTarget(null); setActionId(target.document_id); setError(null)
    try {await request(`/documents/${encodeURIComponent(target.document_id)}`, {method: 'DELETE'}); setNotice(`Đã thu hồi “${target.filename}”. Việc dọn dữ liệu sẽ tiếp tục trong nền.`); if (activeSource?.document_id === target.document_id) setActiveSource(null); await refresh(); void getHealth().then(setHealth)} catch (e) {setError(errorOf(e))} finally {setActionId(null)}
  }
  async function ask(event?: FormEvent) {
    event?.preventDefault(); if (!canAsk) return
    const question = query.trim(); const id = crypto.randomUUID(); setQuery(''); setBusy(true); setError(null)
    setTurns(items => [...items, {id, question}])
    try {
      const result = await request<Answer>('/chat', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({question, ...(!scopeAll && {document_ids: selected}), retrieval_config: config, ...(generationConfig && {generation_config: generationConfig})})})
      setTurns(items => items.map(turn => turn.id === id ? {...turn, result} : turn))
    } catch (e) {setTurns(items => items.map(turn => turn.id === id ? {...turn, error: errorOf(e)} : turn))} finally {setBusy(false); textarea.current?.focus()}
  }
  function toggleDocument(id: string) {setScopeAll(false); setSelected(ids => ids.includes(id) ? ids.filter(item => item !== id) : [...ids, id])}
  function toggleRetriever(key: 'dense' | 'bm25' | 'reranking') {setConfig(current => ({...current, [key]: !current[key]}))}
  const sourceHref = activeSource ? safeSource(activeSource.source_url, activeSource.page_number) : undefined
  const generationBackend = generationConfig?.backend ?? health?.modes?.generation
  const demoMode = health?.modes?.embedding === 'hash' || health?.modes?.reranker === 'lexical' || generationBackend === 'extractive'

  return <div className="app-shell">
    <aside className="library-panel">
      <a className="brand" href="/" aria-label="Vietnamese RAG trang chủ"><span className="brand-symbol"><Icon name="book" size={23}/></span><span>Thư viện<span className="brand-sub">VIETNAMESE RAG</span></span><span className="version-tag">v1</span></a>
      <div className="library-heading"><div><span className="eyebrow">KHÔNG GIAN LÀM VIỆC</span><h2>Tài liệu của bạn <span>{documents.length}</span></h2></div><button className="icon-button" aria-label="Làm mới danh sách tài liệu" onClick={() => {setError(null); void refresh(); void getHealth().then(setHealth)}}><Icon name="refresh" size={17}/></button></div>
      <div className={`upload-zone ${dragging ? 'dragging' : ''} ${uploading ? 'uploading' : ''}`} onDragOver={event => {event.preventDefault(); setDragging(true)}} onDragLeave={() => setDragging(false)} onDrop={event => {event.preventDefault(); setDragging(false); void upload(event.dataTransfer.files)}}>
        <button disabled={uploading} onClick={() => fileInput.current?.click()}><span className="upload-symbol"><Icon name="upload" size={22}/></span><strong>{uploading ? 'Đang tải tài liệu…' : 'Thêm tài liệu'}</strong><span>Kéo thả hoặc chọn từ máy tính</span><small>PDF, DOCX · tối đa 20 MB / file</small></button>
        <input ref={fileInput} type="file" accept=".pdf,.docx,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" multiple hidden onChange={(event: ChangeEvent<HTMLInputElement>) => {void upload(event.target.files)}}/>
      </div>
      <div className="document-search"><Icon name="search" size={16}/><input aria-label="Lọc danh sách tài liệu" placeholder="Tìm tài liệu…" value={docFilter} onChange={event => setDocFilter(event.target.value)}/></div>
      <label className="scope-label"><input type="checkbox" checked={scopeAll} onChange={event => {setScopeAll(event.target.checked); if (event.target.checked) setSelected([])}}/><span>Tìm trong tất cả tài liệu</span><small>{ready.length}</small></label>
      <div className="documents-list" aria-live="polite">
        {loading ? <div className="library-empty"><span className="spinner"/>Đang tải thư viện…</div> : filteredDocuments.length === 0 ? <div className="library-empty"><Icon name="file" size={28}/><strong>{docFilter ? 'Không tìm thấy tài liệu' : 'Thư viện đang trống'}</strong><span>{docFilter ? 'Thử một tên khác.' : 'Thêm tài liệu đầu tiên để bắt đầu.'}</span></div> : filteredDocuments.map(doc => {
          const available = doc.status === 'ready' && doc.available_index_versions.length > 0
          const checked = available && (scopeAll || selected.includes(doc.document_id))
          const source = safeSource(doc.source_url)
          return <div key={doc.document_id} className={`document-item ${checked ? 'selected' : ''}`}>
            <label className="document-select"><input aria-label={`Chọn ${doc.filename}`} type="checkbox" checked={checked} disabled={!available} onChange={() => toggleDocument(doc.document_id)}/><span className={`file-icon ${doc.mime_type === 'application/pdf' ? 'pdf' : 'docx'}`}><Icon name="file" size={19}/></span><span className="document-info"><strong title={doc.filename}>{doc.filename}</strong><span><i className={`status-dot ${doc.status}`}/>{statusNames[doc.status]}{doc.page_count ? ` · ${doc.page_count} trang` : ''}</span></span></label>
            <div className="document-actions">{source && <a href={source} target="_blank" rel="noreferrer" className="icon-button" title="Mở tài liệu nguồn"><Icon name="external" size={14}/></a>}{doc.status === 'failed' && <button className="icon-button" title="Thử xử lý lại" disabled={actionId === doc.document_id} onClick={() => {void retry(doc)}}><Icon name="refresh" size={14}/></button>}<button className="icon-button danger" title={doc.status === 'delete_failed' ? 'Thử xóa lại' : 'Xóa tài liệu'} disabled={actionId === doc.document_id || doc.status === 'deleting'} onClick={() => setDeleteTarget(doc)}><Icon name="trash" size={14}/></button></div>
            {doc.error && <p className="document-error" title={doc.error.code}>{doc.error.message}</p>}
          </div>
        })}
      </div>
      <div className="library-footer"><Icon name="shield" size={16}/><span>Câu trả lời luôn đi cùng bằng chứng.<br/><small>Tài liệu được coi là dữ liệu tham khảo.</small></span></div>
    </aside>

    <main className="main-panel">
      <header className="topbar"><div className="breadcrumb"><span>Không gian tri thức</span><span>/</span><strong>Hỏi đáp tài liệu</strong></div><div className="topbar-right"><span className={`connection-state ${health?.status ?? 'unavailable'}`}><i/>{!health ? 'Đang kết nối' : health.status === 'ok' ? 'Hệ thống sẵn sàng' : health.active_index_version ? 'Dịch vụ đang hạn chế' : 'Đang chờ dữ liệu'}</span><button className={`settings-button ${settingsOpen ? 'active' : ''}`} onClick={() => setSettingsOpen(!settingsOpen)} aria-expanded={settingsOpen}><Icon name="settings" size={17}/><span>Cấu hình</span></button></div></header>
      {settingsOpen && <section className="settings-panel" aria-label="Cấu hình hệ thống"><ModelSettings value={generationConfig} defaultBackend={health?.modes?.generation} onApply={setGenerationConfig} onReset={() => setGenerationConfig(null)}/><div><h3>Cấu hình truy xuất</h3><p>Chọn phương pháp và số đoạn bằng chứng cho câu hỏi tiếp theo.</p></div><div className="retrieval-options">{(['dense', 'bm25', 'reranking'] as const).map(key => <label key={key} className={`toggle-option ${config[key] ? 'enabled' : ''}`}><input type="checkbox" checked={config[key]} onChange={() => toggleRetriever(key)}/><span>{key === 'dense' ? 'Semantic search' : key === 'bm25' ? 'BM25' : 'Reranking'}</span></label>)}<label className="top-k-label">Top K<select value={config.top_k} onChange={event => setConfig({...config, top_k: Number(event.target.value)})}>{[3, 5, 10, 15, 20].map(value => <option key={value}>{value}</option>)}</select></label></div>{!config.dense && !config.bm25 && <p className="validation-message">Cần bật ít nhất Semantic search hoặc BM25.</p>}<p className="settings-note">{health?.active_index_version ? `Index đang phục vụ: ${health.active_index_version}` : 'Index sẽ sẵn sàng sau khi xử lý tài liệu.'}{demoMode ? ' · Đang sử dụng cấu hình demo.' : ''}</p></section>}
      {demoMode && <div className="demo-notice"><span>DEMO</span><p>{[health?.modes?.embedding === 'hash' && 'Tìm kiếm vector mô phỏng', health?.modes?.reranker === 'lexical' && 'xếp hạng bằng từ khóa', generationBackend === 'extractive' && 'trả lời trích xuất'].filter(Boolean).join(' · ')}. Chưa phải kết quả đánh giá mô hình.</p></div>}
      <div className="workspace">
        <div className="conversation" role="log" aria-label="Cuộc hội thoại">
          {turns.length === 0 ? <section className="welcome"><div className="welcome-emblem"><Icon name="book" size={30}/><span/></div><div className="eyebrow">ĐỌC SÂU HƠN. TÌM ĐÚNG HƠN.</div><h1>Tri thức trong tài liệu.<br/><span>Câu trả lời trong tầm tay.</span></h1><p>Đặt câu hỏi bằng tiếng Việt. Khám phá nội dung từ tài liệu<br className="desktop-break"/> của bạn, với trích dẫn rõ ràng đến từng trang.</p><div className="how-it-works"><span><b>01</b> Thêm tài liệu</span><span className="step-line"/><span><b>02</b> Đặt câu hỏi</span><span className="step-line"/><span><b>03</b> Kiểm chứng nguồn</span></div><div className="suggestions"><div className="suggestion-label">BẮT ĐẦU VỚI MỘT CÂU HỎI</div>{suggestions.map((suggestion, index) => <button key={suggestion} onClick={() => {setQuery(suggestion); textarea.current?.focus()}}><span className="suggestion-number">0{index + 1}</span><span>{suggestion}</span><Icon name="plus" size={16}/></button>)}</div></section> : <div className="turns">{turns.map(turn => <article className="turn" key={turn.id}><div className="question-line"><span className="user-avatar">B</span><div><div className="turn-label">BẠN</div><p>{turn.question}</p></div></div><div className="answer-line"><span className="assistant-avatar"><Icon name="book" size={17}/></span><div className="answer-body"><div className="turn-label">THƯ VIỆN <span>· dựa trên tài liệu</span></div>{turn.error ? <div className="inline-error"><strong>Chưa thể hoàn tất yêu cầu</strong><p>{turn.error.message}</p><small>{turn.error.code}{turn.error.requestId ? ` · ${turn.error.requestId}` : ''}</small><button className="text-button" onClick={() => {setQuery(turn.question); textarea.current?.focus()}}>Đặt lại câu hỏi</button></div> : turn.result ? <><div className={`answer-text ${turn.result.status === 'insufficient_evidence' ? 'insufficient' : ''}`}>{turn.result.status === 'insufficient_evidence' && <span className="abstention-label"><Icon name="shield" size={15}/> Chưa đủ bằng chứng</span>}<p>{turn.result.answer}</p></div>{turn.result.citations.length > 0 && <div className="citations"><div className="citation-heading"><Icon name="file" size={14}/><span>NGUỒN THAM KHẢO</span><small>{turn.result.citations.length}</small></div>{turn.result.citations.map(citation => <button className="citation-card" key={citation.source_id} onClick={() => setActiveSource(citation)}><div><span className="citation-id">{citation.source_id}</span><strong>{citation.filename}</strong><span className="page-badge">Trang {citation.page_number}</span><Icon name="external" size={13}/></div><p>“{citation.quote}”</p></button>)}</div>}<details className="trace-details"><summary><Icon name="search" size={13}/>Chi tiết truy xuất<span>{turn.result.retrieval_trace.returned_count} đoạn</span></summary><dl><dt>Index</dt><dd>{turn.result.retrieval_trace.resolved_index_version}</dd><dt>Embedding</dt><dd>{turn.result.retrieval_trace.embedding_model_version}</dd><dt>Mô hình trả lời</dt><dd>{turn.result.retrieval_trace.generation_backend === 'api' ? turn.result.retrieval_trace.llm_model ?? 'LLM API' : turn.result.retrieval_trace.generation_backend === 'extractive' ? 'Trích xuất cục bộ' : 'Không có thông tin'}</dd><dt>Ứng viên / rerank / context</dt><dd>{turn.result.retrieval_trace.candidate_count} / {turn.result.retrieval_trace.reranked_count} / {turn.result.retrieval_trace.context_chunk_count}</dd><dt>Request</dt><dd>{turn.result.request_id}</dd></dl></details></> : <div className="thinking"><span/><span/><span/><small>Đang tìm bằng chứng và chuẩn bị câu trả lời…</small></div>}</div></div></article>)}</div>}
          <div ref={bottom}/>
        </div>
        <div className="composer-area">{error && <div className="error-banner" role="alert"><div><strong>{error.message}</strong><small>{error.code}{error.requestId ? ` · ${error.requestId}` : ''}</small></div><button className="icon-button" aria-label="Đóng thông báo lỗi" onClick={() => setError(null)}><Icon name="close" size={16}/></button></div>}{notice && <div className="notice" role="status"><Icon name="check" size={16}/>{notice}</div>}<form className={`composer ${busy ? 'is-busy' : ''}`} onSubmit={event => {void ask(event)}}><div className="scope-indicator"><span className="scope-chip"><Icon name="book" size={13}/>{scopeAll ? `Tất cả tài liệu (${ready.length})` : `${selected.length} tài liệu đã chọn`}</span><span>{!scopeReady ? 'Thêm hoặc chọn tài liệu sẵn sàng để hỏi' : 'Có dẫn chứng · Có thể kiểm chứng'}</span></div><div className="composer-input"><textarea ref={textarea} aria-label="Câu hỏi về tài liệu" placeholder="Bạn muốn tìm hiểu điều gì từ tài liệu?" value={query} maxLength={4000} rows={2} onChange={event => setQuery(event.target.value)} onKeyDown={event => {if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault(); void ask()}}}/><button className="send-button" type="submit" aria-label="Gửi câu hỏi" disabled={!canAsk}>{busy ? <span className="spinner"/> : <Icon name="arrow" size={21}/>}</button></div><div className="composer-bottom"><span>Enter để gửi <span>·</span> Shift + Enter để xuống dòng</span><span>{query.length > 3500 ? `${query.length}/4000` : 'Vietnamese RAG'}</span></div></form><p className="composer-disclaimer">Hệ thống có thể trả lời chưa chính xác. Hãy đối chiếu bằng chứng trong tài liệu gốc.</p></div>
      </div>
      <footer className="app-footer"><span><i/> {demoMode ? 'Cấu hình demo · embedding/rerank hoặc trả lời trích xuất' : 'Môi trường phát triển · kiểm tra cấu hình model trong README'}</span><span>NGÔN NGỮ: TIẾNG VIỆT</span></footer>
    </main>

    {deleteTarget && <div className="modal-backdrop" onClick={() => setDeleteTarget(null)}><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="delete-title" onClick={event => event.stopPropagation()}><span className="dialog-icon"><Icon name="trash" size={24}/></span><h2 id="delete-title">Xóa tài liệu này?</h2><p><strong>{deleteTarget.filename}</strong> sẽ bị thu hồi khỏi tìm kiếm và xóa khỏi bộ lưu trữ. Index có thể cần một lúc để dựng lại.</p><div className="dialog-actions"><button onClick={() => setDeleteTarget(null)}>Giữ tài liệu</button><button className="delete-button" onClick={() => {void remove()}}>Xóa tài liệu</button></div></section></div>}
    {activeSource && <div className="source-backdrop" onClick={() => setActiveSource(null)}><section className="source-panel" role="dialog" aria-modal="true" aria-labelledby="source-title" onClick={event => event.stopPropagation()}><header><div><span className="eyebrow">BẰNG CHỨNG GỐC</span><h2 id="source-title">{activeSource.filename}</h2><p>Trang {activeSource.page_number} · Phiên bản {activeSource.document_version}</p></div><button className="icon-button" aria-label="Đóng nguồn" onClick={() => setActiveSource(null)}><Icon name="close"/></button></header><blockquote>{activeSource.quote}</blockquote>{sourceHref ? <><a className="open-source" href={sourceHref} target="_blank" rel="noreferrer">Mở PDF trong tab mới <Icon name="external" size={15}/></a><iframe title={`Nguồn ${activeSource.filename} trang ${activeSource.page_number}`} src={sourceHref}/></> : <p className="inline-error">Liên kết nguồn không hợp lệ. Vui lòng kiểm tra lại tài liệu.</p>}</section></div>}
  </div>
}
