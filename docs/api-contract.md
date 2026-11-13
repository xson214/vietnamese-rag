**API contract Vietnamese RAG v1 — bản thiết kế trước triển khai.**

Ngày cập nhật: 13/11/2026. Chủ trì A: tài liệu và health; B: search; C: chat. Hợp đồng máy đọc tại [openapi.yaml](openapi.yaml); quy tắc vòng đời tại [technical-rules.md](technical-rules.md); đánh giá tại [evaluation-protocol.md](evaluation-protocol.md). Đã có implementation MVP; xem [README](../README.md) để biết chế độ demo, adapter thực và phần chưa được kiểm chứng trên môi trường thật. YAML sinh từ server bằng `python scripts/export_openapi.py`. Nếu sửa contract, cập nhật đồng thời schema, ví dụ và nơi sử dụng trong cùng PR.

Đặc tả sử dụng [OpenAPI 3.1.1](https://spec.openapis.org/oas/v3.1.1.html); status HTTP theo [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110.html). Các giới hạn và hành vi nghiệp vụ dưới đây là quyết định thiết kế của dự án.

**Quy ước dùng chung cần được A/B/C áp dụng như nhau.**

- Base path `/api/v1`; JSON UTF-8, timestamp UTC RFC 3339. ID là opaque string, client không tự suy ý nghĩa hay tạo document/index ID.
- Mọi response có `X-Request-ID` do server sinh; JSON có `request_id` khớp header. Ngoại lệ body rỗng 204 và file PDF chỉ có header.
- Request JSON từ chối trường không định nghĩa để phát hiện gõ sai sớm. Client không được phụ thuộc thứ tự trường trong JSON.
- Tên file chỉ là tên hiển thị đã làm sạch, không chứa đường dẫn nội bộ. Không trả API key, filesystem path, stack trace hoặc prompt hệ thống.
- API v1 không streaming, không lưu hội thoại nhiều lượt. `/chat` xử lý một câu hỏi mỗi request.
- MVP dùng trong môi trường demo cục bộ. Xác thực, phân quyền tenant và endpoint quản trị index nằm ngoài hợp đồng này.
- `Idempotency-Key` bắt buộc cho upload và retry; client tạo một key cho một hành động và dùng lại khi gửi lại do lỗi mạng. Server giữ mapping tối thiểu 24 giờ; cùng key nhưng khác fingerprint trả 409. DELETE đã có ngữ nghĩa lặp an toàn, không cần key.
- `null` là chưa có/không áp dụng, không thay bằng `0`, chuỗi rỗng hay con số suy đoán.

| Method | Route | Chủ trì | Thành công |
|---|---|---|---|
| POST | `/api/v1/documents` | A | 202 tạo ingestion; 200 trùng file/key đã nhận |
| GET | `/api/v1/documents` | A | 200 danh sách phân trang |
| GET | `/api/v1/documents/{id}` | A | 200 chi tiết |
| DELETE | `/api/v1/documents/{id}` | A + B | 202 đang xóa; 204 khi đã dọn xong |
| POST | `/api/v1/documents/{id}/retry` | A | 202 retry mới; 200 replay cùng key |
| GET | `/api/v1/documents/{id}/status` | A | 200 tiến độ |
| GET | `/api/v1/documents/{id}/source` | A | 200 PDF chuẩn theo document_version |
| POST | `/api/v1/search` | B | 200 các đoạn truy xuất |
| POST | `/api/v1/chat` | C | 200 answered hoặc insufficient_evidence |
| POST | `/api/v1/models` | C | 200 danh sách model của endpoint người dùng chọn |
| GET | `/api/v1/health` | A | 200 ready/degraded; 503 unavailable |

Route `/source` bổ sung để thực hiện chức năng mở trích dẫn đã có trong kế hoạch. Không còn public route `/ask` hoặc `/jobs`; frontend polling theo document status.

**Upload, danh sách và chi tiết tài liệu có hợp đồng cụ thể như sau.**

`POST /documents` nhận multipart/form-data, đúng một trường `file`. Giới hạn MVP đề xuất: 20 MiB/file, tối đa 300 trang sau chuẩn hóa. MIME được chấp nhận là `application/pdf` và `application/vnd.openxmlformats-officedocument.wordprocessingml.document`; kiểm tra nội dung thực tế, không chỉ đuôi file. File rỗng, mã hóa hoặc hỏng bị từ chối; nếu lỗi chỉ phát hiện trong worker thì tài liệu chuyển `failed` với mã lỗi rõ ràng. PDF scan chưa có OCR cũng chuyển `failed` với `OCR_REQUIRED`.

Upload mới trả 202 `DocumentResponse` ở trạng thái `queued`, kèm `Location: /api/v1/documents/{id}` và `Retry-After: 2`. 202 chỉ xác nhận đã lưu job bền vững, chưa đồng nghĩa index sẵn sàng. Một ID nội bộ `job_id` được trả để đối chiếu log, không có public jobs endpoint.

Cùng key và fingerprint trả 200 với tài liệu/trạng thái hiện tại, không tạo job mới. Fingerprint upload gồm SHA-256 của bytes và tên file đã chuẩn hóa. Khác key nhưng cùng content hash với tài liệu đang tồn tại trả lại tài liệu đó (200), giữ tên file hiện có. Nếu tài liệu đang xóa, trả 410; nếu tài liệu failed, client gọi `/retry`. Sau khi xóa hoàn tất, một upload chủ động với key mới có thể tạo document ID mới. Key cũ không được làm sống lại ID đã xóa.

`GET /documents?limit=20&cursor=...&status=ready`: limit 1–100, mặc định 20; cursor opaque, sắp xếp `created_at DESC, document_id DESC`; response `{request_id, items, next_cursor}`. Filter status tùy chọn. Không trả tài liệu đã xóa hoàn tất; có thể trả deleting/delete_failed để UI theo dõi. Cursor không hợp lệ hoặc dùng lại với filter khác trả 400. Đây là keyset pagination trên dữ liệu sống, không cam kết snapshot danh sách khi status thay đổi giữa các trang.

`GET /documents/{id}` trả `{request_id, document}`. Các trường Document bắt buộc:

| Trường | Ý nghĩa |
|---|---|
| document_id, document_version | ID và phiên bản nội dung; version là số nguyên từ 1 |
| filename, mime_type, size_bytes | Metadata file gốc |
| status | queued / processing / ready / failed / deleting / delete_failed |
| page_count | Số trang PDF chuẩn; null khi chưa biết |
| job_id | Job hiện tại/gần nhất, có thể null |
| available_index_versions | Chỉ gồm các generation published, đang phục vụ và có bản tài liệu này |
| source_url | URL tương đối đến PDF chuẩn có document_version; null nếu chưa sẵn sàng hoặc bị thu hồi |
| error | null hoặc lỗi ingestion/cleanup gần nhất đã làm sạch |
| created_at, updated_at | Timestamp UTC |

`ready` ghi nhận ingestion đã thành công vào ít nhất một generation. Khả năng tìm kiếm hiện tại còn phụ thuộc `available_index_versions`: mảng có thể rỗng sau khi generation bị thu hồi. Client không được coi một status ready là đã có mặt trong mọi index thí nghiệm.

**Theo dõi tiến độ, retry và xóa không được tạo thao tác lặp.**

`GET /documents/{id}/status` trả `request_id`, `document_id`, `document_version`, `status`, `stage`, `progress`, `job_id`, `attempt`, `available_index_versions`, `error`, `updated_at`. Progress là 0–1 hoặc null khi không thể ước lượng; không giả vờ tính chính xác phần trăm. Các stage: queued, validating, converting, extracting, chunking, embedding, indexing, publishing, completed, deleting, failed. UI poll 2 giây khi đang xử lý/xóa, tăng backoff khi lỗi dịch vụ và dừng khi trạng thái terminal.

`POST /documents/{id}/retry` không có body, có Idempotency-Key. Chỉ tạo attempt mới khi status=`failed`; tái sử dụng document_version và cấu hình ingestion của lần thất bại. Cùng key đã nhận được replay trước khi kiểm tra lại status để không biến retry mạng thành 409. Key mới khi queued/processing/ready trả 409 `INVALID_DOCUMENT_STATE`; deleting/delete_failed/deleted trả 410. Retry không phải API đổi embedding/chunking; việc tạo generation thực nghiệm do công cụ nội bộ quản lý.

`DELETE /documents/{id}` lập tức lưu tombstone thu hồi tài liệu, đặt deleting và vô hiệu hóa mọi generation chứa tài liệu đó. Response 202 gồm `request_id`, `document_id`, `status: deleting`, `job_id`, kèm Retry-After. Worker dọn file gốc/PDF chuẩn/text/chunk, Qdrant, BM25 và metadata nội dung. Ledger/tombstone tối thiểu được giữ riêng để bảo đảm xóa lặp an toàn.

- Nếu gọi DELETE khi deleting: trả 202 cùng job, không tạo job song song.
- Nếu delete_failed: DELETE tiếp tục cleanup idempotent còn thiếu và trả 202.
- Nếu đã hoàn tất: DELETE trả 204; GET detail/status/source hoặc retry ID này trả 410.
- ID chưa từng biết trả 404. UI polling thấy 410 `DOCUMENT_DELETED` coi như xóa xong.
- Chỉ trả 204 sau khi mọi nơi lưu nội dung đã được xác nhận dọn sạch. Tombstone không chứa filename, quote, text hay đường dẫn nguồn.

Với index bất biến, xóa tài liệu có thể làm index active không còn phục vụ được. Default search/chat trả 503 `INDEX_NOT_READY` cho đến khi worker publish generation mới từ các tài liệu còn lại. Chọn explicit generation đã thu hồi trả 409 `INDEX_VERSION_UNAVAILABLE`, không fallback ngầm. Quy tắc này tránh dùng corpus khác với phiên bản benchmark được yêu cầu.

**Xem nguồn phải gắn với phiên bản tài liệu.**

`GET /documents/{id}/source?document_version=1` bắt buộc có version; trả PDF chuẩn, Content-Type application/pdf, Content-Disposition inline và Cache-Control no-store. Không có canonical PDF trả 409 `SOURCE_NOT_READY`; version không tồn tại trả 404; tài liệu bị thu hồi trả 410. DOCX được hiển thị bằng bản PDF chuyển đổi đã lưu cố định. MVP trả toàn bộ PDF, chưa yêu cầu Range/206.

Citation dùng trang vật lý PDF bắt đầu từ 1. UI có thể mở `source_url#page=12`. Hệ thống không cam kết thu hồi bytes đã được client tải trước khi xóa; mọi lần truy cập mới và response chưa phát hành phải kiểm tra tombstone. Các request chat/search đang chạy recheck generation trước khi trả kết quả; bị thu hồi giữa chừng trả 409 `SOURCE_SET_CHANGED`.

**Search và chat dùng chung lựa chọn corpus và retrieval_config.**

| Trường | Quy tắc |
|---|---|
| document_ids | Bỏ qua: tất cả tài liệu hợp lệ trong generation được chọn. Nếu có: 1–100 ID duy nhất, không nhận [] hoặc null |
| index_version | Tùy chọn; bỏ qua thì pin active generation lúc bắt đầu; có thì dùng đúng generation đó |
| retrieval_config.dense | Boolean, mặc định true |
| retrieval_config.bm25 | Boolean, mặc định true |
| retrieval_config.reranking | Boolean, mặc định true |
| retrieval_config.top_k | Số đoạn đầu ra cuối cùng; nguyên 1–20, mặc định 5 |

Phải bật dense hoặc bm25; không cho phép cả hai false. Không tự điều chỉnh cấu hình người dùng khi dependency lỗi. Nếu một nhánh được yêu cầu không sẵn sàng, trả lỗi dependency thay vì âm thầm chạy nhánh còn lại. Với BM25-only, không gọi embedding model nhưng vẫn trả metadata của generation.

Server kiểm tra toàn bộ explicit document_ids trước khi truy xuất: không tồn tại → 404; đang/đã xóa → 410; chưa được index trong generation → 409 `DOCUMENT_NOT_INDEXED`. Không bỏ qua ID sai để trả kết quả một phần. Index không tồn tại → 404; đang build, retired, revoked hoặc failed → 409. Không có active generation phục vụ → 503.

Mỗi request pin cả generation, dense collection, BM25 snapshot, query embedder và document versions tương ứng. Đổi active pointer giữa request không được đổi một thành phần của request đã bắt đầu. Response trả `retrieval_trace` gồm resolved_index_version, corpus_snapshot_id, embedding_model_version, chunking_config_id, effective_config và số ứng viên trước/sau rerank. `effective_config` phải điền đầy đủ default đã resolve.

Mặc định nội bộ: dense lấy tối đa 20, BM25 tối đa 20; RRF khử trùng rồi giữ tối đa 30; khi reranking bật thì chấm danh sách đó trước khi lấy top_k. Không reranking thì lấy top_k theo thứ hạng fusion/nhánh đơn. Các tham số ứng viên, tokenizer, RRF constant và revision reranker được version trong cấu hình server/benchmark, không nhận tùy ý từ client MVP. Chat có thể dùng ít hơn top_k nếu bị giới hạn context, ghi số đoạn thực dùng trong trace.

`POST /search` nhận `query` (1–4000 Unicode code points sau trim, không chỉ whitespace) cùng các trường trên. Trả `request_id`, `hits`, `retrieval_trace`. Mỗi hit có `chunk_id`, document_id/document_version, filename, text, source_spans, rank và `scores` gồm dense/bm25/fusion/rerank; điểm nhánh không chạy là null. Các điểm này là relevance score, không phải xác suất đáp án đúng. Search trả 200 hits=[] nếu truy vấn hợp lệ nhưng không có kết quả; không dùng answer status.

SourceSpan có page_number, start_offset, end_offset và quote; offset theo Unicode code points của text chuẩn trên trang, 0-based, khoảng [start,end). Python slicing phù hợp, JavaScript phải xử lý code points thay vì UTF-16 code units. Chuỗi quote phải khớp chính xác span; end lớn hơn start. Chunk qua nhiều trang có nhiều SourceSpan.

**Chat giữ nguyên cấu trúc người dùng đề xuất và bổ sung trace tái lập.**

Request minh họa (ID chỉ là fixture, không phải dữ liệu đã chạy):

```json
{
  "question": "Các nguyên tắc hoạt động của hệ thống là gì?",
  "document_ids": ["doc_001", "doc_002"],
  "retrieval_config": {
    "dense": true,
    "bm25": true,
    "reranking": true,
    "top_k": 5
  }
}
```

Chat nhận thêm `generation_config` tùy chọn, riêng từng request:

```json
{
  "question": "Availability Zone là gì?",
  "generation_config": {
    "backend": "api",
    "base_url": "https://provider.example/v1",
    "model": "model-id-do-provider-cung-cap",
    "api_key": "<key-nhap-trong-giao-dien>"
  }
}
```

Không có trường này thì dùng cấu hình mặc định của server. `backend=extractive` dùng trích xuất không cần key; `backend=api` bắt buộc base_url và model. Không gửi null. Key là trường write-only SecretStr, không trả lại, không ghi database/log, không làm thay đổi cấu hình các tab khác. Frontend chỉ giữ key trong RAM của tab; tải lại trang mất cấu hình. Trace bổ sung `generation_backend`, `llm_model` (null khi extractive) và `prompt_version`, không chứa key hoặc URL có thông tin đăng nhập.

`POST /models` nhận `{base_url, api_key}` khi người dùng chủ động bấm tải danh sách; backend gọi `GET {base_url}/models`, trả `{request_id, models: ["model-id", ...]}`. Nếu provider không hỗ trợ list thì cho nhập model ID thủ công. URL giới hạn HTTPS công khai hoặc HTTP loopback, không nhận userinfo/query/fragment/địa chỉ metadata hoặc LAN; không follow redirect. Lỗi mới gồm INVALID_MODEL_ENDPOINT (422), MODEL_AUTH_FAILED (502), MODEL_LIST_BAD_RESPONSE (502). Không trả raw error body của provider vì có thể chứa key. Đây là chức năng cho bản demo cục bộ; không mở proxy này ra Internet cho người dùng không tin cậy.

Response answered bắt buộc có answer không rỗng, citations ít nhất một phần tử, confidence và retrieval_trace. Citation gồm source_id, document_id, document_version, filename, page_number, quote, source_span và source_url. Mỗi citation thuộc một trang; nếu khẳng định cần hai trang, trả hai citation. source_id duy nhất trong request, do backend cấp; answer dùng marker `[src_001]` để liên kết với mảng citations. Mọi marker phải trỏ đến citation và mọi citation phải được sử dụng; kiểm tra thêm quan hệ bằng chứng–khẳng định theo rubric, không chỉ ID hợp lệ.

```json
{
  "request_id": "req_001",
  "status": "answered",
  "answer": "Hệ thống trả lời dựa trên tài liệu được cung cấp. [src_001]",
  "citations": [
    {
      "source_id": "src_001",
      "document_id": "doc_001",
      "document_version": 1,
      "filename": "document.pdf",
      "page_number": 12,
      "quote": "Trả lời dựa trên tài liệu.",
      "source_span": {"start_offset": 0, "end_offset": 26},
      "source_url": "/api/v1/documents/doc_001/source?document_version=1"
    }
  ],
  "confidence": null,
  "retrieval_trace": {
    "resolved_index_version": "idx_001",
    "corpus_snapshot_id": "corpus_001",
    "embedding_model_version": "model_demo@revision_001",
    "chunking_config_id": "chunk_001",
    "effective_config": {"dense": true, "bm25": true, "reranking": true, "top_k": 5},
    "candidate_count": 8,
    "reranked_count": 8,
    "returned_count": 5,
    "context_chunk_count": 5
  }
}
```

Implementation hiện chỉ trả `confidence: null`; YAML phản ánh đúng phạm vi này. Khi đã có bộ ước lượng hiệu chỉnh và đánh giá độc lập, mới mở rộng schema để trả `{level: low|medium|high, score: 0..1, calibration_id: ...}`. Object `{level: "unknown", score: null, calibration_id: null}` cũng chỉ được thêm khi client có nhu cầu; không cho level high/medium/low đi cùng score null. Không dùng raw cosine, BM25, sigmoid reranker hoặc lời tự chấm của LLM làm confidence.

Response thiếu bằng chứng trả HTTP 200, status insufficient_evidence, answer giải thích ngắn, citations=[], confidence=null, vẫn có retrieval_trace. Không có gold evidence trong runtime; đây là quyết định của evidence gate được hiệu chỉnh bằng dev set. Câu hỏi cùng chủ đề nhưng nguồn thiếu chi tiết được hỏi cũng có thể thuộc trường hợp này.

```json
{
  "request_id": "req_002",
  "status": "insufficient_evidence",
  "answer": "Tài liệu hiện tại chưa cung cấp đủ thông tin để trả lời.",
  "citations": [],
  "confidence": null,
  "retrieval_trace": {
    "resolved_index_version": "idx_001",
    "corpus_snapshot_id": "corpus_001",
    "embedding_model_version": "model_demo@revision_001",
    "chunking_config_id": "chunk_001",
    "effective_config": {"dense": true, "bm25": true, "reranking": true, "top_k": 5},
    "candidate_count": 0,
    "reranked_count": 0,
    "returned_count": 0,
    "context_chunk_count": 0
  }
}
```

Không trả status answered nếu citation không hợp lệ. Generation gửi JSON Schema gồm đúng status/answer/source_ids và enum ID được cấp. Chỉ khi provider báo rõ không hỗ trợ structured schema mới thương lượng xuống json_object. Nếu LLM trả malformed output hoặc citation ngoài context, yêu cầu tạo lại một lần có giới hạn; vẫn lỗi thì trả 502 `LLM_BAD_RESPONSE` hoặc `CITATION_VALIDATION_FAILED`, không ngụy trang thành thiếu bằng chứng. Tổng timeout áp dụng cho mọi attempt; tối đa ba HTTP calls khi cần cả thương lượng và repair. Trace có generation_attempts, response_format và response_repaired. Không có key/raw provider content trong trace hoặc lỗi.

Chuẩn hóa an toàn gồm bỏ code fence JSON bao toàn bộ nội dung, nhận text parts/parsed JSON, loại metadata model không được tin cậy, chuẩn hóa source_ids chuỗi đơn/loại lặp. Nếu model đã trả answered cùng marker thì có thể khôi phục danh sách ID từ marker, sau đó vẫn kiểm tra từng ID thuộc context. Không suy ra answer/status hoặc tự bổ sung marker. Phản hồi bị cắt trả LLM_OUTPUT_TRUNCATED, model refusal/content_filter trả LLM_REFUSED; các ca này không repair tự động. Timeout, Qdrant/BM25 lỗi và LLM API lỗi phải đi theo error envelope.

**Lỗi HTTP dùng một envelope chung để frontend không phải đoán.**

```json
{
  "request_id": "req_error_001",
  "status": "error",
  "error": {
    "code": "DOCUMENT_NOT_INDEXED",
    "message": "Tài liệu chưa có trong phiên bản index được chọn.",
    "retryable": false,
    "details": [{"field": "document_ids[0]", "reason": "doc_001 không thuộc idx_002"}]
  }
}
```

| HTTP | Mã lỗi nghiệp vụ |
|---|---|
| 400 | MALFORMED_REQUEST, INVALID_CURSOR |
| 404 | DOCUMENT_NOT_FOUND, DOCUMENT_VERSION_NOT_FOUND, INDEX_VERSION_NOT_FOUND |
| 409 | IDEMPOTENCY_CONFLICT, INVALID_DOCUMENT_STATE, DOCUMENT_NOT_INDEXED, INDEX_VERSION_UNAVAILABLE, SOURCE_SET_CHANGED, SOURCE_NOT_READY |
| 410 | DOCUMENT_DELETING, DOCUMENT_DELETED |
| 413 | FILE_TOO_LARGE |
| 415 | UNSUPPORTED_MEDIA_TYPE |
| 422 | VALIDATION_ERROR, INVALID_DOCUMENT |
| 429 | RATE_LIMITED, kèm Retry-After nếu server giới hạn |
| 500 | INTERNAL_ERROR |
| 502 | LLM_BAD_RESPONSE, CITATION_VALIDATION_FAILED, LLM_OUTPUT_TRUNCATED, LLM_REFUSED, UPSTREAM_ERROR |
| 503 | DEPENDENCY_UNAVAILABLE, INDEX_NOT_READY, CONFIGURATION_MISSING |
| 504 | UPSTREAM_TIMEOUT |

Error.retryable cho biết có nên gửi lại cùng hành động sau backoff; không đồng nghĩa hệ thống tự sửa được mọi lỗi. SOURCE_SET_CHANGED có thể retry bằng request mới; việc dùng index_version đã revoked vẫn không hợp lệ. Frontend không retry vô hạn và không biến lỗi HTTP thành thông báo thiếu bằng chứng.

`GET /health` là ngoại lệ envelope khi 503: vẫn trả HealthResponse gồm request_id, status=ok/degraded/unavailable, checked_at, active_index_version hoặc null, components và modes. Modes ghi backend embedding/reranker/generation để client nhận biết demo. Components liệt kê sqlite, file_storage, worker, dense, bm25, llm; mỗi trạng thái thuộc ok/degraded/unavailable/configured/not_configured. llm=configured chỉ xác nhận cấu hình, không chứng minh provider hoạt động và không phát sinh lời gọi có tính phí. 200 khi registry có generation published và worker chạy; đây là kiểm tra readiness cục bộ, không gọi model/provider/Qdrant để kiểm tra chất lượng hoặc sức khỏe sâu. 503 khi index chưa có hoặc thiếu cấu hình LLM cần cho chat. Lỗi đọc SQLite/storage vẫn là lỗi kỹ thuật. Không lộ secrets trong health.

**Checklist trước khi bắt đầu module implementation.**

- A/B/C xác nhận schema Document/SourceSpan/SearchHit/ChatResponse và fixture JSON cùng version.
- Validate OpenAPI, request/response ví dụ và các trường hợp sai schema: top_k=0, false/false, document_ids=[], unknown field, answered không citation, insufficient_evidence có confidence.
- Kiểm tra semantic bằng contract tests khi triển khai: filter không được bỏ qua ID sai; query embedder khớp pinned index; citation quote khớp source_span; source URL đúng version.
- Có fixture và test quy trình cho upload duplicate, retry khi đang chạy, delete giữa ingestion, delete giữa chat, lỗi một store khi cleanup và index switch giữa request.
- Đặc tả JSON Schema không tự chứng minh lookup ID, độ đúng quote, số trang tồn tại, uniqueness source_id hay ngữ nghĩa citation; những điều đó phải kiểm tra ở runtime và đánh giá.
