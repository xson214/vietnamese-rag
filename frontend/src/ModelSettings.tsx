import {useRef, useState} from 'react'
import {ApiError, request} from './api'
import type {GenerationConfig} from './api'

type Props = {
  value: GenerationConfig | null
  defaultBackend?: string
  onApply: (value: GenerationConfig) => void
  onReset: () => void
}

function validEndpoint(value: string) {
  try {
    const url = new URL(value)
    const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname)
    return !url.username && !url.password && !url.search && !url.hash && (url.protocol === 'https:' || (url.protocol === 'http:' && loopback))
  } catch {return false}
}

export default function ModelSettings({value, defaultBackend, onApply, onReset}: Props) {
  const [draft, setDraft] = useState<GenerationConfig>(value ?? {backend: defaultBackend === 'api' ? 'api' : 'extractive', base_url: '', model: '', api_key: ''})
  const [models, setModels] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [showKey, setShowKey] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const revision = useRef(0)

  function update(patch: Partial<GenerationConfig>) {
    revision.current++
    if ('base_url' in patch || 'api_key' in patch) setModels([])
    setDraft(previous => ({...previous, ...patch})); setError(''); setNotice('')
  }

  async function loadModels() {
    if (loading) return
    if (!validEndpoint(draft.base_url.trim())) {setError('Nhập base URL HTTPS, hoặc HTTP localhost cho model cục bộ. URL không được chứa tài khoản hay API key.'); return}
    setError(''); setNotice(''); setLoading(true)
    const version = revision.current
    try {
      const result = await request<{request_id: string; models: string[]}>('/models', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({base_url: draft.base_url.trim().replace(/\/+$/, ''), api_key: draft.api_key})})
      if (version !== revision.current) return
      setModels(result.models)
      setNotice(result.models.length ? `Đã tải ${result.models.length} model. Chọn model trong danh sách bên dưới.` : 'Provider chưa trả danh sách model. Bạn có thể nhập model ID trực tiếp.')
    } catch (e) {
      if (version !== revision.current) return
      setError(e instanceof ApiError ? `${e.message}${e.requestId ? ` · ${e.requestId}` : ''} Bạn vẫn có thể nhập model ID trực tiếp.` : 'Chưa tải được model. Bạn có thể nhập model ID trực tiếp.')
    } finally {setLoading(false)}
  }

  function apply() {
    if (draft.backend === 'api') {
      if (!validEndpoint(draft.base_url.trim())) {setError('Nhập base URL HTTPS hợp lệ, hoặc HTTP localhost cho model cục bộ.'); return}
      if (!draft.model.trim()) {setError('Chọn hoặc nhập model ID trước khi áp dụng.'); return}
    }
    const config: GenerationConfig = draft.backend === 'extractive'
      ? {backend: 'extractive', base_url: '', model: '', api_key: ''}
      : {...draft, base_url: draft.base_url.trim().replace(/\/+$/, ''), model: draft.model.trim()}
    setDraft(config); onApply(config); setShowKey(false); setError('')
    setNotice(config.backend === 'api' ? 'Đã áp dụng cho câu hỏi tiếp theo trong tab này. Chưa gửi yêu cầu kiểm tra tới model.' : 'Đã chuyển về trả lời trích xuất cục bộ, không dùng API key.')
  }

  function clear() {
    revision.current++
    setDraft({backend: 'extractive', base_url: '', model: '', api_key: ''})
    setModels([]); setShowKey(false); setError(''); setNotice('Đã xóa API key khỏi cấu hình của tab và quay về mặc định máy chủ.'); onReset()
  }

  return <section className="model-settings" aria-labelledby="model-settings-title">
    <div className="model-settings-heading"><div><h3 id="model-settings-title">Mô hình trả lời</h3><p>Dùng LLM để tổng hợp câu trả lời từ bằng chứng; chế độ trích xuất chỉ lấy nội dung có sẵn.</p></div><span className={`model-status ${value?.backend === 'api' ? 'api-active' : ''}`}>{value ? value.backend === 'api' ? 'API trong tab' : 'Trích xuất trong tab' : 'Mặc định máy chủ'}</span></div>
    <div className="model-form-grid">
      <label className="model-field"><span>Chế độ trả lời</span><select value={draft.backend} onChange={event => update({backend: event.target.value as GenerationConfig['backend']})}><option value="extractive">Trích xuất cục bộ — không cần key</option><option value="api">LLM qua API tương thích OpenAI</option></select></label>
      {draft.backend === 'api' && <>
        <label className="model-field"><span>Loại endpoint</span><select aria-label="Chọn loại endpoint" value={draft.base_url === 'http://127.0.0.1:11434/v1' ? 'local' : 'custom'} onChange={event => update({base_url: event.target.value === 'local' ? 'http://127.0.0.1:11434/v1' : ''})}><option value="custom">Nhập base URL của provider</option><option value="local">Ollama trên máy này</option></select></label>
        <label className="model-field model-field-wide"><span>Base URL</span><input type="url" maxLength={2048} autoComplete="off" value={draft.base_url} onChange={event => update({base_url: event.target.value})} placeholder="https://provider.example/v1" spellCheck={false}/><small>Nhập base URL, không thêm /chat/completions. HTTP chỉ dùng cho localhost.</small></label>
        <label className="model-field model-field-wide"><span>API key <small>Để trống nếu server cục bộ không yêu cầu</small></span><div className="key-input"><input type={showKey ? 'text' : 'password'} maxLength={8192} autoComplete="off" aria-label="API key cho model" value={draft.api_key} onChange={event => update({api_key: event.target.value})} placeholder="Nhập key của provider" spellCheck={false}/><button type="button" onClick={() => setShowKey(!showKey)} aria-label={showKey ? 'Ẩn API key' : 'Hiện API key'}>{showKey ? 'Ẩn' : 'Hiện'}</button></div></label>
        <div className="model-field model-field-wide"><div className="model-label-row"><label htmlFor="generation-model">Model ID</label><button type="button" className="load-models-button" disabled={loading || !draft.base_url.trim()} onClick={() => {void loadModels()}}>{loading ? 'Đang tải…' : 'Tải danh sách model'}</button></div>{models.length > 0 && <select aria-label="Chọn model từ provider" value={models.includes(draft.model) ? draft.model : ''} onChange={event => update({model: event.target.value})}><option value="">Chọn model từ danh sách</option>{models.map(model => <option key={model} value={model}>{model}</option>)}</select>}<input id="generation-model" maxLength={200} value={draft.model} onChange={event => update({model: event.target.value})} placeholder="Chọn ở trên hoặc nhập model ID trực tiếp" spellCheck={false} autoComplete="off"/><small>Provider cần hỗ trợ chat/completions và phản hồi JSON. Có thể phát sinh phí theo model.</small></div>
      </>}
    </div>
    <p className="model-privacy">API key chỉ giữ trong bộ nhớ của tab, không lưu vào trình duyệt hay cơ sở dữ liệu. Key được gửi tới backend và endpoint bạn chọn khi tải model hoặc đặt câu hỏi. Tải lại trang sẽ xóa cấu hình này.</p>
    {error && <p className="model-feedback model-error" role="alert">{error}</p>}
    {notice && <p className="model-feedback" role="status">{notice}</p>}
    <div className="model-settings-actions"><button type="button" className="apply-model-button" onClick={apply} disabled={loading}>Áp dụng trong tab này</button><button type="button" onClick={clear}>Xóa key và dùng mặc định</button></div>
  </section>
}
