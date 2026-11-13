**Vietnamese RAG — hỏi đáp tài liệu tiếng Việt có nguồn và số trang.**

Bản MVP gồm FastAPI, React/TypeScript, ingestion PDF/DOCX, OCR ảnh JPG/PNG/WebP và PDF scan, chunking, dense retrieval + BM25 + RRF, reranking, chat có citation, xử lý thiếu bằng chứng, version index và bộ chạy đánh giá. Đây là code triển khai ban đầu; các mục nghiên cứu trong [kế hoạch](KE_HOACH_DU_AN.md) cần tiếp tục bằng corpus thật và gold được kiểm tra thủ công.

Địa chỉ sau khi khởi chạy: [giao diện](http://127.0.0.1:5173), [Swagger API](http://127.0.0.1:8000/docs). Với Docker Compose, giao diện ở [cổng 8080](http://127.0.0.1:8080).

Mặc định dùng **embedding thật chạy cục bộ** `intfloat/multilingual-e5-small`, revision `614241f622f53c4eeff9890bdc4f31cfecc418b3`, kết hợp BM25. Embedding không cần API key; lần đầu cần tải model. Reranker vẫn lexical, trả lời mặc định trích đoạn; chọn LLM API trong Cấu hình để sinh câu trả lời. Nhãn demo vẫn xuất hiện khi reranker hoặc generation còn ở chế độ demo. Không tự fallback sang hash khi model lỗi. Confidence hiện luôn `null`.

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
.\.venv\Scripts\python.exe -m pip install "torch==2.15.0" --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-neural.lock
npm.cmd --prefix frontend ci
.\.venv\Scripts\python.exe scripts/make_samples.py
.\.venv\Scripts\python.exe scripts/setup_ocr.py
.\.venv\Scripts\python.exe scripts/setup_embedding.py
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

**Chụp ảnh tài liệu hoặc đơn thuốc để hỏi bằng OCR.**

1. Windows: cài dependencies từ `backend/requirements.lock` như trên; có sẵn Python binding Tesseract trong `.venv`. Chạy `scripts/setup_ocr.py` bằng Python của `.venv` để tải dữ liệu `vie+eng` từ repository Tesseract chính thức (revision và SHA-256 được khóa). Không tải ảnh của bạn lên dịch vụ nào trong bước setup này.
2. Khởi động lại backend sau khi cài. Với máy đang chạy trong phiên triển khai, OCR và dữ liệu ngôn ngữ đã được cài vào `.venv` và `data/runtime/tessdata`.
3. Bấm **Thêm tài liệu** để chọn JPG/JPEG, PNG hoặc WebP, hoặc **Chụp ảnh tài liệu** trên điện thoại có hỗ trợ camera. HEIC/ảnh động chưa hỗ trợ; chuyển sang JPG/PNG trước khi tải.
4. Chụp đủ trang, thẳng, đủ sáng, chữ rõ và không bị lóa. Giới hạn 20 MiB/file và 24 triệu điểm ảnh. Chờ trạng thái **Sẵn sàng** và badge **OCR**.
5. Chọn riêng ảnh cần hỏi, ví dụ “Đọc các tên thuốc được ghi trên đơn” hoặc “Theo đơn, cách dùng được ghi như thế nào?”. Mở nguồn để đối chiếu chữ/con số trên ảnh gốc; ảnh được hiển thị thành PDF một trang, không thay bằng văn bản OCR giả lập.

OCR chạy **cục bộ, không cần API key**. Muốn câu trả lời tổng hợp mạch lạc hơn, có thể bật Gemini/LLM ở mục cài đặt bên dưới. Khi bật API, câu hỏi và các đoạn text OCR được truy xuất sẽ gửi đến provider đã chọn; OCR không gửi ảnh gốc ra ngoài. Giữ chế độ trích xuất để xử lý hoàn toàn cục bộ.

Nếu PDF scan có lớp OCR cũ bị lỗi tiếng Việt, bản mới tự phát hiện các trang có dấu hiệu hỏng và đọc lại từ ảnh. Với tài liệu đã tải trước khi cập nhật, bấm **Đọc lại tài liệu**, chờ **Sẵn sàng** rồi hỏi lại. Thao tác tạo phiên bản tài liệu/index mới, giữ nguyên citation và nguồn cũ; upload lại cùng file không thay thế index. Nếu đọc lại thất bại, dùng nút thử xử lý lại sau khi kiểm tra thông báo lỗi.

Không gian làm việc có vùng tài liệu rộng hơn, tên file xuống dòng, tìm theo tên và thao tác chọn/bỏ chọn nhanh. Để hỏi riêng một file: bấm **Bỏ chọn**, lọc tên rồi **Chọn kết quả**. Trên điện thoại, bấm **Tài liệu** để mở danh sách gần toàn màn hình.

Tesseract ưu tiên chữ in; chữ viết tay trên đơn thuốc hoặc ảnh mờ không được bảo đảm đọc chính xác. Token có tín hiệu nhận dạng thấp được thay bằng `[không rõ]`. Khi câu hỏi về thuốc/liều liên quan phần này, hệ thống yêu cầu ảnh rõ hơn và không đoán. Confidence của OCR không phải xác suất liều/tên thuốc đúng; OCR vẫn có thể sai ở phần không bị che. Sản phẩm chỉ hỗ trợ đọc nội dung ghi trên ảnh, không kê đơn hoặc quyết định tăng/giảm/đổi/ngừng thuốc. Hỏi bác sĩ/dược sĩ khi không rõ nội dung dùng thuốc.

PDF scan và PDF hỗn hợp được OCR ở trang có ảnh nhưng không trích xuất được text, tối đa 20 trang OCR/lần; trang text tiếp tục đọc bằng pypdf. Metadata `extraction` cho biết phương pháp, trang OCR và cảnh báo. Bản này chưa OCR thêm vùng ảnh nếu trang đã có text (ví dụ chỉ một header), và không bảo đảm nhận diện bảng phức tạp.

Với Linux native, cài Tesseract CLI cùng dữ liệu `vie`/`eng` theo [hướng dẫn Tesseract](https://tesseract-ocr.github.io/tessdoc/Installation.html), rồi đặt `OCR_DATA_DIR` trỏ đúng thư mục `.traineddata`. Windows cũng có thể dùng Tesseract CLI nếu đặt `TESSERACT_PATH`. Docker image đã có CLI và hai gói ngôn ngữ, không cần chạy setup Windows trong container.

| Biến OCR | Mặc định | Ý nghĩa |
|---|---|---|
| OCR_ENABLED | true | Bật/tắt OCR ảnh và PDF scan |
| OCR_LANGUAGES | vie+eng | Ngôn ngữ Tesseract |
| OCR_DATA_DIR | data/runtime/tessdata với native | Thư mục model ngôn ngữ; Docker dùng đường dẫn hệ thống |
| TESSERACT_PATH | tesseract | Executable CLI nếu đã cài; Windows không có CLI dùng binding |
| OCR_TIMEOUT | 60 | Timeout giây cho subprocess OCR mỗi trang |
| OCR_MIN_CONFIDENCE | 60 | Ngưỡng che token nhận dạng thấp, không phải medical confidence |
| OCR_MAX_PAGES | 20 | Số trang scan tối đa cho một tài liệu |
| MAX_IMAGE_PIXELS | 24000000 | Giới hạn kích thước ảnh/render |

Thiếu engine hoặc model ngôn ngữ sẽ báo lỗi trong trạng thái tài liệu; cài engine/chạy setup rồi **Thử xử lý lại**. Script `scripts/make_ocr_sample.py` tạo ảnh tiếng Việt thử nghiệm không chứa thông tin bệnh nhân. Xem [thiết kế OCR](docs/ocr-engine.md) để biết preprocessing, giới hạn và lỗi cụ thể.

**Docker Compose cung cấp thêm Qdrant và bộ chuyển DOCX.**

```powershell
Copy-Item .env.example .env
docker compose up --build
```

Mở http://127.0.0.1:8080. Backend dùng cổng 8000, Qdrant chỉ ở mạng nội bộ; dữ liệu giữ trong Docker volumes. Docker image backend có LibreOffice và font. File `.env` được Compose nạp; khi chạy Python trực tiếp cần đặt biến môi trường trong shell — ứng dụng không tự đọc `.env`.

Docker Engine phải hoạt động trước khi chạy. `docker compose config --quiet` đã được kiểm tra trong môi trường phát triển; build/run container chưa được xác nhận vì Docker Engine trên máy hiện chưa chạy. Giữ volumes khi dừng demo bằng `docker compose down`.

**Embedding mặc định và nâng cấp reranking.**

Đã chuyển mặc định từ vector hash sang embedding E5 thật chạy cục bộ, vector chuẩn hóa L2 384 chiều, kết hợp BM25. Phiên kiểm chứng ngày 13/11/2026 đã dựng index mới cho 8 tài liệu / 432 chunks, chạy tìm kiếm dense-only qua HTTP và kiểm tra citation; 169 tests và 2 subtests đạt. Đây là xác minh chức năng, chưa phải benchmark độ chính xác trên gold. Các index đã xuất bản giữ nguyên để đối chiếu; không đưa model cache hoặc tài liệu người dùng lên GitHub.

Các thay đổi đi kèm gồm OCR ảnh/PDF scan và phát hiện lớp OCR cũ bị hỏng; nút **Đọc lại tài liệu** tạo phiên bản mới mà vẫn giữ nguồn cũ; vùng chọn tài liệu rộng hơn, tên file xuống dòng và thao tác chọn/lọc thuận tiện. Câu hỏi liều dùng theo khoảng tuổi chỉ trích điều kiện sử dụng rõ trong nguồn và yêu cầu dữ kiện còn thiếu, không tự tính liều.

Model embedding đã là mặc định cho các tài liệu mới. Cache model ở `data/runtime/models`. Nếu corpus được tạo bằng hash trước đây, dừng backend và tạo index mới (không ghi đè bản cũ):

```powershell
$env:PYTHONPATH='backend'
.\.venv\Scripts\python.exe -m app.reindex --config experiments/configs/multilingual-e5.json
```

Khởi động lại backend rồi mở Chi tiết truy xuất: embedding phải chứa `sentence_transformers` và tên E5. Chọn generation API không thay embedding. Có thể chọn `EMBEDDING_BACKEND=hash` riêng cho kiểm thử/demo offline; đây không còn là mặc định ứng dụng.

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

Model tải ở lần build đầu, cần mạng và đủ RAM/VRAM. Embedding E5 dùng tiền tố query/passage đúng vai trò. Manifest lưu commit model; input vượt giới hạn tokenizer bị từ chối thay vì cắt âm thầm. `CHUNK_SIZE` mặc định 120, overlap 20, tính theo whitespace token; kiểm tra thêm giới hạn tokenizer model. Dependency neural được khóa tại `backend/requirements-neural.lock`; model/reranker khác cần benchmark riêng.

Compose mặc định `INSTALL_NEURAL=true`, `EMBEDDING_BACKEND=sentence_transformers`; đặt thêm `RERANKER_BACKEND=cross_encoder` nếu muốn chạy reranker neural rồi build lại. Chế độ này dùng Qdrant. Qdrant/container chưa được kiểm chứng trên máy hiện tại; unit/API tests dùng hash tường minh để không tải model, provider tests dùng mock. Smoke embedding thật được kiểm tra riêng trên corpus cục bộ.

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

- Upload giới hạn 20 MiB và 300 trang; ảnh tối đa 24 triệu điểm ảnh, tối đa 20 trang cần OCR. Giữ trang vật lý PDF, NFC/LF và Unicode code point offsets. DOCX chuyển thành PDF chuẩn cố định; ảnh và PDF scan dùng OCR cục bộ. Bảng phức tạp/chữ viết tay chưa được bảo đảm nhận dạng chính xác.
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

Kiểm tra OCR thật sau khi chạy setup OCR và khởi động backend (chỉ dùng dữ liệu mẫu, không chứa thông tin bệnh nhân):

```powershell
.\.venv\Scripts\python.exe scripts/make_ocr_sample.py
.\.venv\Scripts\python.exe scripts/smoke_ocr.py
```

Lệnh kiểm tra upload ảnh và PDF scan, chờ OCR, hỏi đáp và xác minh nguồn trang 1. Đây là smoke test chữ in rõ, không phải đánh giá độ chính xác trên đơn thuốc viết tay thực tế.

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
