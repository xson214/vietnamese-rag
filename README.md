**Vietnamese RAG — hỏi đáp tài liệu tiếng Việt có nguồn và số trang.**

Bản MVP gồm FastAPI, React/TypeScript, ingestion PDF/DOCX, chunking, dense retrieval + BM25 + RRF, reranking, chat có citation, xử lý thiếu bằng chứng, version index và bộ chạy đánh giá. Đây là code triển khai ban đầu; các mục nghiên cứu trong [kế hoạch](KE_HOACH_DU_AN.md) cần tiếp tục bằng corpus thật và gold được kiểm tra thủ công.

Địa chỉ sau khi khởi chạy: [giao diện](http://127.0.0.1:5173), [Swagger API](http://127.0.0.1:8000/docs). Với Docker Compose, giao diện ở [cổng 8080](http://127.0.0.1:8080).

Mặc định là **demo cục bộ**: vector hash, reranker lexical và trả trích đoạn, không tải model/không gọi LLM. Chế độ này kiểm tra được luồng dữ liệu và nguồn nhưng không chứng minh chất lượng Semantic Search hoặc LLM. Health, trace và giao diện có nhãn demo. Adapter neural thật và LLM API được cung cấp riêng qua cấu hình, không tự fallback khi lỗi. Confidence hiện luôn `null`.

**Chạy cục bộ trên Windows với Python 3.12 và Node 22.**

Lấy mã nguồn lần đầu rồi vào thư mục dự án:

```powershell
git clone https://github.com/xson214/vietnamese-rag.git
cd vietnamese-rag
```

Nếu đã có repo, vào đúng thư mục và chạy `git pull --ff-only` để cập nhật. Tại thư mục dự án, tạo môi trường và cài dependency nếu chưa có:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock
npm.cmd --prefix frontend ci
.\.venv\Scripts\python.exe scripts/make_samples.py
```

Terminal thứ nhất chạy backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

Terminal thứ hai chạy giao diện:

```powershell
npm.cmd --prefix frontend run dev -- --host 127.0.0.1
```

Mở http://127.0.0.1:5173, upload `data/samples/quy-trinh-demo.pdf`, chờ trạng thái Sẵn sàng, hỏi “Hồ sơ đăng ký được xử lý trong bao nhiêu ngày?”. Kiểm tra nguồn ở trang 1, rồi hỏi một câu ngoài tài liệu để thử từ chối. DOCX mẫu ở cùng thư mục cần LibreOffice. Local không có LibreOffice sẽ báo `CONVERTER_UNAVAILABLE`, không tự tạo số trang giả. Cài LibreOffice từ nhà cung cấp rồi đặt `LIBREOFFICE_PATH` nếu `soffice` chưa có trong PATH.

Local mặc định dùng snapshot NumPy và SQLite trong `data/runtime`; không cần Qdrant để thử pipeline. Chỉ chạy **một process/worker** trên một DATA_DIR; file lease ngăn hai tiến trình cùng ghi. Không dùng `--workers 2` hoặc nhiều replica với thiết kế SQLite hiện tại. Backend phục vụ local; frontend proxy API nên không cần mở CORS rộng.

**Docker Compose cung cấp thêm Qdrant và bộ chuyển DOCX.**

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Mở http://127.0.0.1:8080. Backend dùng cổng 8000, Qdrant chỉ ở mạng nội bộ; dữ liệu giữ trong Docker volumes. Docker image backend có LibreOffice và font. File `.env` được Compose nạp; khi chạy Python trực tiếp cần đặt biến môi trường trong shell — ứng dụng không tự đọc `.env`.

Docker Engine phải hoạt động trước khi chạy. `docker compose config --quiet` đã được kiểm tra trong môi trường phát triển; build/run container chưa được xác nhận vì Docker Engine trên máy hiện chưa chạy. Giữ volumes khi dừng demo bằng `docker compose down`.

**Bật Semantic Search và reranking neural thực.**

Local cài thêm thư viện:

```powershell
.\.venv\Scripts\python.exe -m pip install "sentence-transformers>=3,<7"
$env:EMBEDDING_BACKEND='sentence_transformers'
$env:EMBEDDING_MODEL='intfloat/multilingual-e5-small'
$env:RERANKER_BACKEND='cross_encoder'
$env:RERANKER_MODEL='BAAI/bge-reranker-v2-m3'
$env:CHUNK_SIZE='120'
$env:CHUNK_OVERLAP='20'
```

Model tải ở lần build đầu, cần mạng và đủ RAM/VRAM. Embedding E5 dùng tiền tố query/passage đúng vai trò. Manifest lưu commit model đã resolve; input vượt giới hạn tokenizer bị từ chối thay vì cắt âm thầm. `CHUNK_SIZE` của các chiến lược hiện tính theo whitespace token; luôn kiểm tra thêm giới hạn tokenizer model. Đặt `EMBEDDING_REVISION`/`RERANKER_REVISION` bằng commit hash để khóa từ đầu. Dependency neural chưa có lock thực nghiệm; sau khi cài trên máy mục tiêu cần lưu freeze và kết quả vào manifest thí nghiệm.

Với Compose, đặt `INSTALL_NEURAL=true`, `EMBEDDING_BACKEND=sentence_transformers`, `RERANKER_BACKEND=cross_encoder` trong `.env`, rồi build lại. Chế độ này dùng Qdrant. Model neural/Qdrant server chưa được chạy thực nghiệm trong phiên bàn giao; các tests mặc định dùng demo, các provider tests dùng mock.

**Bật sinh câu trả lời bằng LLM API.**

Để trả lời tổng hợp thay vì chỉ lấy trích đoạn, cấu hình model theo một trong hai cách: nhập trên giao diện cho riêng tab đang mở, hoặc đặt biến môi trường làm mặc định cho backend.

**Cách 1 — nhập Gemini API trên giao diện (dễ bắt đầu).**

1. Chạy backend và frontend theo các lệnh ở trên. Mở http://127.0.0.1:5173 (hoặc http://127.0.0.1:8080 với Compose).
2. Vào [Google AI Studio](https://aistudio.google.com/apikey), tạo/lấy Gemini API key của bạn.
3. Trên trang RAG, bấm **Cấu hình → Mô hình trả lời**. Ở **Chế độ trả lời**, chọn **LLM qua API tương thích OpenAI**.
4. Chọn loại endpoint **Nhập base URL của provider**, rồi điền theo bảng bên dưới.
5. Bấm **Tải danh sách model** và chọn model Gemini hỗ trợ chat/JSON. Nếu provider không hỗ trợ danh sách, nhập đúng model ID từ tài khoản của bạn; các model khả dụng có thể khác nhau theo tài khoản/thời điểm.
6. Bấm **Áp dụng trong tab này**. Việc áp dụng chỉ lưu cấu hình trong RAM, chưa gọi thử model; yêu cầu gọi API phát sinh khi tải model hoặc gửi câu hỏi.
7. Upload PDF/DOCX, đợi **Sẵn sàng**, chọn tài liệu rồi hỏi. Nếu tài liệu đã có sẵn, chỉ cần hỏi lại. Mở **Chi tiết truy xuất** để kiểm tra backend generation là `api` và model đúng tên đã chọn.

| Ô trên giao diện | Giá trị cần điền cho Gemini |
|---|---|
| Base URL | `https://generativelanguage.googleapis.com/v1beta/openai` |
| API key | Gemini API key của bạn từ Google AI Studio |
| Model ID | Model chat được trả từ danh sách hoặc đúng ID trong tài khoản Gemini |

Không thêm `/chat/completions` vào Base URL: ứng dụng tự nối route đó. Endpoint trên được Google công bố trong [tài liệu Gemini tương thích OpenAI](https://ai.google.dev/gemini-api/docs/openai).

Với provider khác, dùng Base URL/API key/model do provider đó cấp. Với Ollama chạy native cùng máy backend, có thể chọn **Ollama trên máy này**, endpoint `http://127.0.0.1:11434/v1`, nhập tên model đã cài trên Ollama và để key trống nếu server không yêu cầu.

Key chỉ ở bộ nhớ của tab và request tương ứng; không lưu localStorage/sessionStorage/cookie hay database, không trả lại trong API response. Key được gửi tới backend và provider đã chọn khi tải danh sách/đặt câu hỏi. Tải lại trang xóa cấu hình tab. Cấu hình bằng giao diện không đổi default của server hoặc tab khác; đây là cấu hình generation, không thay embedding/index. Nếu chạy backend trong Docker, `localhost` trỏ vào container; lựa chọn Ollama localhost dành cho backend chạy native. Không mở endpoint proxy model của bản local này ra Internet.

Đã sửa chế độ trích xuất cho slide PDF: nối dòng xuống hàng trong câu, bỏ tiêu đề dạng câu hỏi, nối các chunk chồng nhau và ưu tiên định nghĩa đúng thực thể. Nguồn/offset vẫn dùng text gốc. Chế độ trích xuất vẫn là heuristic, không có khả năng tổng hợp/hiểu tương đương LLM.

**Cách 2 — đặt API mặc định cho backend bằng PowerShell.**

Dừng backend cũ bằng Ctrl+C trong terminal đang chạy nó, rồi thực hiện các lệnh dưới đây tại thư mục dự án trong **cùng một terminal**. Model ID cần là model bạn đã xác nhận khả dụng trong tài khoản. Dùng nhập key ẩn để tránh đưa key vào lịch sử lệnh:

```powershell
$env:GENERATION_BACKEND='api'
$env:LLM_BASE_URL='https://generativelanguage.googleapis.com/v1beta/openai'
$env:LLM_MODEL=Read-Host 'Nhap Gemini model ID'
$geminiKey=Read-Host 'Nhap Gemini API key' -AsSecureString
$env:LLM_API_KEY=[System.Net.NetworkCredential]::new('', $geminiKey).Password
Remove-Variable geminiKey
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --workers 1
```

Chạy frontend ở terminal khác như hướng dẫn ban đầu. Trên giao diện để **Mặc định máy chủ** (hoặc bấm **Xóa key và dùng mặc định** nếu đã áp dụng cấu hình tab). Biến môi trường chỉ tác động tới tiến trình backend được mở từ terminal đó. Đóng terminal rồi mở lại thì phải cấu hình lại; ứng dụng native không tự đọc `.env`.

Với Docker Compose, sao chép `.env.example` sang `.env`, điền các biến sau vào `.env` rồi chạy `docker compose up --build`. Đây là file cấu hình cục bộ có giữ key nếu bạn chọn cách này; `.env` đã được gitignore. Không điền key thật vào `.env.example` hoặc README:

```dotenv
GENERATION_BACKEND=api
LLM_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
LLM_MODEL=THAY_BANG_MODEL_ID_THUC_TE
LLM_API_KEY=THAY_BANG_API_KEY_CUA_BAN
```

Các giá trị viết hoa ở trên là placeholder, phải thay bằng giá trị thật trước khi chạy. Nếu chỉ muốn key riêng từng tab, giữ cấu hình mặc định extractive và dùng Cách 1.

API provider cần hỗ trợ `/chat/completions` và structured JSON hoặc JSON object. Ví dụ biến môi trường cho server model cục bộ tương thích:

```powershell
$env:GENERATION_BACKEND='api'
$env:LLM_BASE_URL='http://127.0.0.1:11434/v1'
$env:LLM_MODEL='<model-da-cai-tren-server>'
$env:LLM_API_KEY=''
```

Tài liệu trong context được gửi tới provider đã cấu hình; dùng provider phù hợp với dữ liệu của nhóm. Prompt coi tài liệu là dữ liệu không đáng tin, model không có tool, citation ID/filename/trang/quote được backend kiểm tra. Việc kiểm tra marker/nguồn hợp lệ không chứng minh mọi claim được bằng chứng hỗ trợ; cần chấm ngữ nghĩa theo rubric. Không có khóa hay provider thật được cấu hình trong repo.

Generation gửi JSON Schema rõ ràng bằng `response_format: json_schema`, gồm status, answer và source_ids thuộc context. Nếu provider báo rõ không hỗ trợ schema, thử lại bằng `json_object`. Phản hồi sai JSON/schema/citation được yêu cầu tạo lại tối đa một lần, trong cùng timeout chung; tối đa ba HTTP calls nếu cần cả thương lượng định dạng lẫn sửa phản hồi (tối đa hai phản hồi model thành công). Đây là request bổ sung có thể tốn token. Không retry vì key sai, quota, timeout, model refusal hoặc output bị cắt. Không tự đổi sang demo khi API lỗi. Xem [chi tiết sửa tương thích Gemini](docs/fix-gemini-response-schema.md).

**Lỗi thường gặp khi chạy và điền API.**

| Hiện tượng | Cách xử lý |
|---|---|
| Vẫn thấy “Trích đoạn liên quan” | Cấu hình generation còn ở extractive; chọn API và bấm Áp dụng, hoặc kiểm tra biến môi trường rồi restart backend |
| Reload trang mất key/model | Đúng với cấu hình riêng từng tab; nhập lại và Áp dụng, hoặc dùng cấu hình backend ở Cách 2 |
| API key không hợp lệ / MODEL_AUTH_FAILED | Kiểm tra đúng key của provider, quyền truy cập model và quota của tài khoản |
| Không tìm thấy model hoặc endpoint | Kiểm tra đúng Base URL, không lặp `/chat/completions`, nhập đúng model ID khả dụng |
| Không tải được danh sách model | Provider có thể không hỗ trợ route list; thử model ID thủ công từ tài khoản của bạn |
| LLM_BAD_RESPONSE | Cập nhật code và restart backend; bản mới có schema/repair. Nếu vẫn lỗi, giữ mã lỗi/request ID để chẩn đoán; không đưa key vào báo lỗi |
| INDEX_NOT_READY / Đang chờ dữ liệu | Upload tài liệu và đợi Sẵn sàng; kiểm tra lỗi ingestion nếu xử lý thất bại |
| Cổng 8000 đã được dùng | Dừng backend cũ trong terminal bằng Ctrl+C trước khi chạy bản mới |

**Index bất biến và vòng đời tài liệu đã có đường chạy.**

- Upload giới hạn 20 MiB và 300 trang; giữ trang vật lý PDF, NFC/LF và Unicode code point offsets. DOCX chuyển thành PDF chuẩn cố định. OCR, bảng phức tạp và PDF scan chưa được hỗ trợ.
- Dense snapshot và BM25 sử dụng cùng tập chunk. Với corpus MVP, BM25 tính từ text/chunk snapshot bất biến ở mỗi query, chưa có inverted index tối ưu riêng.
- Build staging rồi publish active pointer trong SQLite; mỗi request pin phiên bản và query embedder. Tài liệu mới tạo generation mới, các generation cũ vẫn chọn được bằng index_version.
- DELETE thu hồi mọi generation chứa tài liệu ngay; cleanup chạy bằng job bền vững, retry DELETE khi delete_failed. Request đang chạy recheck trước trả; không hồi sinh tài liệu qua ingestion retry.
- Corpus còn tài liệu thì dựng successor sạch; khoảng chờ trả INDEX_NOT_READY. Corpus rỗng thì clear active pointer. Retry ingestion giữ cấu hình của lần tạo tài liệu.
- Staging sau crash có registry để phát hiện/dọn; startup phục hồi job đang chạy. Chạy một worker và shutdown sạch trước bảo trì.
- Benchmark/export do người dùng tải ra ngoài runtime là bản sao riêng; người quản lý cần áp dụng chính sách xóa cho các bản sao đó. Server không thể thu hồi nội dung đã được client tải trước DELETE.

**Tạo generation mới để so sánh chunking/embedding.**

Dừng backend trước khi chạy CLI; giữ cùng DATA_DIR và QDRANT_URL nếu dùng Qdrant:

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m app.reindex --config experiments/configs/offline-hybrid.json
```

CLI dùng cùng writer lease, từ chối khi có server hoặc job chưa hoàn tất; trả index_version mới và chuyển active pointer. Đổi file config để thử `fixed`, `recursive`, `heading` hoặc model khác; các artifact cũ vẫn tồn tại nếu chưa bị thu hồi. Khởi động lại backend rồi dùng `index_version` cụ thể trong `/search`, `/chat` hoặc runner. Không sửa artifact của version đã publish. Đổi cấu hình chỉ bằng restart không tự rebuild tài liệu đã ready: phải chạy reindex.

**Kiểm thử và benchmark.**

```powershell
.\.venv\Scripts\python.exe -m pytest -c pyproject.toml -q
.\.venv\Scripts\python.exe -m ruff check backend evaluation scripts
.\.venv\Scripts\python.exe scripts/export_openapi.py --check
npm.cmd --prefix frontend run build
```

Với hai server đang chạy và PDF mẫu đã tạo, kiểm tra HTTP thật:

```powershell
.\.venv\Scripts\python.exe scripts/smoke.py
$smokeIndex = Get-Content evaluation/results/smoke-index.txt
.\.venv\Scripts\python.exe -m evaluation.run --dataset evaluation/results/smoke-gold.json --index-version $smokeIndex --output evaluation/results/my-smoke-run --allow-fixtures
```

Output directory benchmark phải chưa tồn tại để không ghi đè run cũ. Smoke tạo đúng hai câu fixture để kiểm tra phần mềm; kết quả không đại diện cho chất lượng nghiên cứu. Bộ 180 câu gold, annotation/review, benchmark model thật và calibration confidence vẫn cần thực hiện theo [protocol](docs/evaluation-protocol.md). Runner có Evidence Recall@5, MRR@10, all-evidence, abstention precision/recall_all, lỗi và latency; correctness/citation ngữ nghĩa được để trống cho người chấm.

GitHub Actions chạy tests/lint, kiểm tra OpenAPI không lệch code và build frontend. Contract YAML sinh từ implementation bằng `python scripts/export_openapi.py`; HTTP contract đọc ở [api-contract.md](docs/api-contract.md). Schema hiện triển khai confidence=null; schema score tương lai trong tài liệu chỉ áp dụng khi có calibrator đã được đánh giá.

**Phân chia mã nguồn và công việc tiếp theo.**

| Phần | Vị trí | Người phụ trách theo kế hoạch |
|---|---|---|
| API/schema, ingestion, storage/lifecycle | backend/app/main.py, schemas.py, ingestion.py, store.py | A |
| Chunking, dense/BM25/RRF/reranker | backend/app/chunking.py, retrieval.py | B + A |
| Generation, citation, prompt | backend/app/generation.py | C |
| Upload/chat/source viewer | frontend/src | C |
| Metrics, benchmark, fixtures | evaluation | B; cả nhóm kiểm tra gold |

Các module đã có implementation và kiểm thử cơ bản. Việc còn cần dữ liệu/môi trường thật: chạy DOCX qua LibreOffice, build Compose, chạy model neural/LLM provider, kiểm tra hình ảnh giao diện trên trình duyệt, tạo gold có review và đánh giá chất lượng. Repository của nhóm: [xson214/vietnamese-rag](https://github.com/xson214/vietnamese-rag).
