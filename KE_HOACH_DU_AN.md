**Kế hoạch đề xuất: Vietnamese RAG cho nhóm 3 người**

Dựa trên yêu cầu trong ảnh: đọc PDF/DOCX tiếng Việt, semantic search kết hợp BM25 và reranking, trả lời có nguồn và số trang, từ chối khi thiếu bằng chứng, nghiên cứu chunking/embedding/retrieval.

Giả định để lập lịch: 8 tuần, mỗi người 12–15 giờ/tuần; tổng khoảng 288–360 giờ. Nhóm chọn một lĩnh vực, thu thập 30–50 tài liệu có quyền sử dụng. Mọi chỉ tiêu chất lượng dưới đây là mục tiêu đề xuất, chưa phải kết quả đo. Chốt cấu hình phần cứng và ngân sách gọi LLM trong tuần 1.

Bản kế hoạch đã cập nhật theo yêu cầu hoàn thiện contract trước khi viết mã ứng dụng. Khi triển khai, dùng [API contract](docs/api-contract.md) và [OpenAPI](docs/openapi.yaml) để thống nhất payload, HTTP status và lỗi; dùng [quy tắc kỹ thuật](docs/technical-rules.md) cho index/lifecycle/bảo vệ nguồn và [quy trình đánh giá](docs/evaluation-protocol.md) cho dataset/metric. Thay đổi contract phải cập nhật đồng thời các tài liệu liên quan và được người dùng API review.

**Phạm vi bàn giao cần giữ đủ bốn yêu cầu chức năng trong ảnh.**

| Mức | Nội dung |
|---|---|
| Bắt buộc | Upload PDF có text và DOCX; trạng thái xử lý và báo lỗi |
| Bắt buộc | Chuẩn hóa tiếng Việt; chia đoạn có ánh xạ về tài liệu/trang |
| Bắt buộc | BM25, dense search, hybrid fusion, reranking; bật/tắt theo cấu hình |
| Bắt buộc | Hỏi đáp tiếng Việt; chọn phạm vi tài liệu; nguồn, số trang, đoạn bằng chứng |
| Bắt buộc | Mở đúng tài liệu/trang nguồn; từ chối khi bằng chứng không đủ |
| Bắt buộc | Xóa tài liệu và loại khỏi cả hai index; không index lặp khi retry |
| Bắt buộc | Bộ đánh giá, kết quả so sánh, README cài đặt, demo tái lập |
| Mở rộng sau MVP | OCR PDF scan, bảng phức tạp, streaming, hội thoại nhiều lượt, tài khoản/phân quyền |

MVP phục vụ demo cục bộ trong phạm vi một nhóm người dùng. Nếu triển khai công khai cần bổ sung xác thực, phân quyền tài liệu và giới hạn sử dụng trước khi mở truy cập. PDF scan chưa có OCR phải báo rõ chưa hỗ trợ, không xử lý thành công với nội dung rỗng.

**Kiến trúc triển khai là một monorepo với backend dạng modular monolith.**

```text
Upload PDF/DOCX
  -> Lưu file gốc và phiên bản
  -> DOCX: chuyển thành PDF chuẩn, lưu cố định
  -> Trích xuất theo trang -> làm sạch -> chunk có nguồn
  -> Dense index (Qdrant) + BM25 index + metadata (SQLite)

Câu hỏi + phạm vi tài liệu
  -> Dense top 20 + BM25 top 20
  -> RRF + khử trùng theo chunk_id -> tối đa 30 ứng viên
  -> Rerank -> tối đa 5 đoạn, trong giới hạn context
  -> Kiểm tra đủ bằng chứng
       -> Không đủ: trả trạng thái insufficient_evidence
       -> Đủ: LLM sinh trả lời và chọn source_id
              -> kiểm tra citation -> hiển thị câu trả lời và nguồn
```

Các giá trị top-k là cấu hình khởi đầu để benchmark. RRF kết hợp thứ hạng, tránh cộng trực tiếp điểm BM25 và cosine vốn khác thang. Reranker chỉ chấm ứng viên đã truy xuất. Nguồn tham khảo: [Qdrant hybrid queries](https://qdrant.tech/documentation/hybrid-queries/), [Sentence Transformers retrieve/rerank](https://sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html).

**Bộ công nghệ đề xuất ưu tiên dễ tích hợp và đo lường.**

| Thành phần | Lựa chọn |
|---|---|
| Backend | Python + FastAPI + Pydantic; khóa phiên bản dependency sau khi chạy smoke test |
| Frontend | React + TypeScript + Vite; upload, chat, xem nguồn |
| Đọc tài liệu | pypdf cho PDF text; LibreOffice headless chuyển DOCX sang PDF; kiểm tra layout trên corpus mẫu |
| Metadata/file | SQLite + thư mục lưu file có volume; một worker xử lý ingestion và trạng thái job lưu bền |
| Dense index | Qdrant chạy bằng Docker, collection riêng theo phiên bản embedding/index |
| BM25 | rank-bm25 cho corpus nhỏ; lưu/rebuild index theo snapshot đang hoạt động |
| Embedding baseline | intfloat/multilingual-e5-small |
| Embedding đối chứng | BAAI/bge-m3, chỉ dùng dense embedding trong thí nghiệm so sánh này |
| Reranker | BAAI/bge-reranker-v2-m3; đo tốc độ trên máy nhóm ngay tuần 1 |
| LLM | Một model API có khả năng trả lời tiếng Việt; bọc bằng interface để thay provider; giữ cố định model khi đánh giá |
| Kiểm thử/vận hành | pytest, Ruff, frontend typecheck/build, GitHub Actions, Docker Compose |

E5 cần tiền tố `query:`/`passage:` theo model card và có giới hạn đầu vào; không để văn bản bị cắt âm thầm. BGE-M3 và reranker nêu trên là ứng viên đa ngôn ngữ, chất lượng tiếng Việt cần được đo trên dữ liệu của nhóm. Xem [E5 model card](https://huggingface.co/intfloat/multilingual-e5-small), [BGE-M3 model card](https://huggingface.co/BAAI/bge-m3), [reranker model card](https://huggingface.co/BAAI/bge-reranker-v2-m3).

Tuần 1 cần chạy thử embedding, reranking và một yêu cầu LLM trên máy thật; ghi RAM/VRAM, thời gian và chi phí. Nếu máy không đáp ứng, giảm số ứng viên hoặc dùng inference endpoint trong ngân sách đã chốt. Không loại bỏ reranking khỏi yêu cầu cuối chỉ vì baseline chưa dùng nó.

**Phân công theo module, có một người chịu trách nhiệm chính cho từng phần.**

| ID | Module và đầu việc | Người chính | Điều kiện hoàn thành |
|---|---|---|---|
| M01 | API contract/OpenAPI, hợp đồng dữ liệu, cấu hình, logging, scaffold backend và CI | A; B/C cùng chốt schema | Chốt endpoint, request/response/error và ví dụ hợp lệ trước mã ứng dụng; CI kiểm tra contract trên PR |
| M02 | Upload, lưu file, hash, trạng thái job, retry, giới hạn loại/dung lượng file | A | Upload trùng/retry không tạo bản index lặp; lỗi có thông báo |
| M03 | PDF extraction, DOCX conversion, làm sạch, metadata theo trang | A | Các file mẫu giữ tiếng Việt và ánh xạ đúng nguồn/trang |
| M04 | Fixed-size, recursive, heading-aware chunking; version cấu hình | A | Mọi chunk giữ provenance; không vượt giới hạn model |
| M05 | Embedding adapter, batch/cache, dense index, tìm kiếm có filter và index version | B | Query và corpus dùng cùng model/revision; đổi model/chunking dựng generation mới, không ghi đè bản đang phục vụ |
| M06 | BM25, chuẩn hóa/tách từ, fusion RRF, khử trùng | B | Trả được dense-only, BM25-only, hybrid với cùng phạm vi dữ liệu |
| M07 | Reranking, context selection, giới hạn token | B | Xếp hạng lại ứng viên và ghi latency; không cắt mất nguồn |
| M08 | API chat, prompt, LLM adapter, citation, từ chối thiếu bằng chứng và confidence | C | Trả schema ổn định; citation thuộc context; không tự sinh số trang; confidence null khi chưa hiệu chỉnh và đánh giá |
| M09 | UI upload/status/chat, chọn tài liệu, xem nguồn và trạng thái từ chối | C | Người dùng đi trọn luồng và mở đúng trang PDF |
| M10 | Đồng bộ xóa/reindex, worker recovery, đóng gói chạy demo | A; B hỗ trợ index | Thu hồi ngay trên mọi generation; retry dọn file/SQLite/Qdrant/BM25 an toàn; metadata nội dung xóa sau khi cleanup hoàn tất |
| M11 | Dataset gold, runner, metric và báo cáo thí nghiệm | B chủ trì; cả nhóm chia việc | Chạy lại có config, dataset version, output và metric |
| M12 | Kiểm thử tích hợp, README, hướng dẫn demo, báo cáo cuối | C chủ trì; A/B đóng góp | Cài trên môi trường sạch và demo theo kịch bản thành công |

A phụ trách dữ liệu/backend tài liệu và vận hành; B phụ trách truy xuất và nghiên cứu; C phụ trách câu trả lời và trải nghiệm. Để cân bằng M11, A làm thí nghiệm chunking và kiểm tra nguồn, B làm embedding/retrieval, C chấm chất lượng trả lời/citation. Mục tiêu 180 câu đánh giá, mỗi người soạn 60 câu và người khác kiểm tra chéo.

**Hợp đồng tích hợp phải chốt ngay tuần 1 để ba người làm song song.**

| Đối tượng | Trường tối thiểu |
|---|---|
| Document | document_id, document_version, filename, content_hash, mime_type, status; tham chiếu file/PDF chuẩn chỉ lưu nội bộ |
| Chunk | chunk_id, document_id, document_version, text, section, source_spans, chunking_config_id |
| SourceSpan | page_number, start_offset, end_offset; trang bắt đầu từ 1, offset theo Unicode code point trong text chuẩn của trang, khoảng [start, end) |
| Index manifest | index_version, embedding_model_version, chunking_config_id, danh sách document_version và corpus snapshot; thêm version preprocessing/tokenizer cần để tái lập |
| SearchHit | chunk và provenance, điểm/thứ hạng từng bước nếu có; response xác nhận index_version đã dùng |
| Chat response | request_id, status: answered/insufficient_evidence, answer, citations, confidence; chỉ HTTP 200 cho hai kết quả nghiệp vụ này |
| Error response | Envelope lỗi riêng theo contract với HTTP 4xx/5xx; lỗi dịch vụ không phải insufficient_evidence |
| Citation | source_id, document_id, document_version, filename, page_number, quote; bằng chứng ở nhiều trang tách citation theo trang |

Backend lấy tên file/trang từ metadata đáng tin cậy; LLM chỉ tham chiếu ID được cấp. Chunk qua nhiều trang phải giữ nhiều source span. Ngay từ đầu lưu text chuẩn theo trang và phiên bản để gold evidence không lệ thuộc chunk ID.

| API | Method | Chủ trì | Mục đích |
|---|---|---|---|
| /api/v1/documents | POST | A | Upload PDF/DOCX, nhận tác vụ ingestion bất đồng bộ |
| /api/v1/documents | GET | A | Liệt kê tài liệu, phân trang và lọc trạng thái |
| /api/v1/documents/{id} | GET | A | Chi tiết tài liệu, phiên bản và trạng thái |
| /api/v1/documents/{id} | DELETE | A; B hỗ trợ index | Thu hồi tài liệu và dọn dữ liệu ở mọi store |
| /api/v1/documents/{id}/retry | POST | A | Retry ingestion thất bại theo quy tắc idempotency |
| /api/v1/documents/{id}/status | GET | A | Poll trạng thái và lỗi xử lý |
| /api/v1/documents/{id}/source?document_version=... | GET | A | Xem đúng PDF chuẩn của phiên bản được citation tham chiếu |
| /api/v1/search | POST | B | Kiểm tra retrieval độc lập với document_ids, retrieval_config và index_version |
| /api/v1/chat | POST | C | Hỏi đáp RAG có citation, abstention và confidence |
| /api/v1/health | GET | A | Kiểm tra hệ thống theo ngữ nghĩa health trong contract |

Endpoint source bổ sung phục vụ chức năng mở trích dẫn đã có trong phạm vi MVP. Public API dùng tiền tố /api/v1 thống nhất; trạng thái job được truy cập qua tài liệu, không cung cấp route /jobs riêng trong bản này.

A cung cấp 5 tài liệu mẫu và chunk JSON; B cung cấp mock SearchHit; C dựng UI và generator dựa trên mock. Request chat dùng question, document_ids và retrieval_config gồm dense, bm25, reranking, top_k như yêu cầu. API contract quy định rõ phạm vi khi bỏ document_ids, validation khi chọn tài liệu chưa sẵn sàng, giới hạn top_k và cách chọn index_version; frontend/backend không tự đặt quy ước khác nhau.

Document có các trạng thái queued, processing, ready, failed, deleting, delete_failed. Retry ingestion chỉ áp dụng trạng thái failed; retry xóa đi qua DELETE, không làm sống lại tài liệu. Sau khi xóa hoàn tất, chỉ còn tombstone tối thiểu phục vụ idempotency và nhận biết tài liệu đã xóa; metadata chứa nội dung phải được dọn. Một tài liệu sẵn sàng trong một generation chưa có nghĩa đã sẵn sàng trong mọi generation; kiểm tra membership ở index_version được chọn theo contract.

Hệ thống MVP dùng một worker ghi index. Mỗi index_version xác định một generation với manifest bất biến gồm corpus/document versions, embedding_model_version và chunking_config_id. Dựng dense và BM25 trong staging, kiểm chứng đồng bộ rồi cập nhật active pointer trong một giao dịch SQLite. Request ghim generation khi bắt đầu và dùng đúng query embedder của generation đó; không trộn dense/BM25 thuộc hai generation hoặc âm thầm chuyển sang active mới. Có thể yêu cầu explicit index_version để so sánh hai cấu hình.

Khi nhận DELETE, lưu trạng thái thu hồi bền trước và chặn tài liệu khỏi truy xuất/xem nguồn ngay trên mọi generation. Sau đó dọn Qdrant, BM25, file storage, text và metadata theo checklist có retry; giữ ledger đủ lâu để tiếp tục khi tiến trình lỗi, chỉ xóa metadata nội dung sau khi các bước dọn đã xác nhận. Worker phải kiểm tra tombstone trước publish; request đang chạy phải kiểm tra lại nguồn trước khi trả để tránh hồi sinh hoặc trả nội dung vừa bị thu hồi. Generation bị thay đổi do thu hồi không còn dùng để tuyên bố benchmark nguyên trạng có thể tái lập.

confidence mặc định là null. Chỉ trả object/score khi bộ ước lượng đã được hiệu chỉnh trên dữ liệu phù hợp và đánh giá trên dữ liệu độc lập; level cũng không được tự đặt từ cảm nhận của LLM. Giá trị 0.91 trong ví dụ người dùng chỉ minh họa schema. Điểm cosine/BM25/reranker hoặc sigmoid của chúng không tự trở thành xác suất câu trả lời đúng.

**Cách xử lý nguồn và thiếu bằng chứng quyết định chất lượng sản phẩm.**

- PDF dùng số trang vật lý bắt đầu từ 1; phân biệt với số in trên trang nếu cần.
- DOCX chuyển sang một PDF chuẩn và lưu nguyên bản PDF đó. UI ghi rõ số trang thuộc bản chuyển đổi. Không suy số trang từ số đoạn DOCX: python-docx không tự render/phân trang. Xem [python-docx](https://python-docx.readthedocs.io/en/stable/api/text.html) và [LibreOffice PDF export](https://help.libreoffice.org/latest/en-GB/text/shared/guide/pdf_params.html).
- Giữ text nguồn để trích dẫn; normalization phục vụ tìm kiếm phải có ánh xạ về nguồn. Chuẩn hóa/tách từ BM25 nhất quán giữa query và corpus; tránh bỏ dấu tiếng Việt mặc định.
- Chỉ đưa ứng viên đủ liên quan vào context, rồi kiểm tra context có chứa thông tin mà câu hỏi yêu cầu. Có tài liệu cùng chủ đề chưa có nghĩa là đủ đáp án.
- Chọn ngưỡng từ chối trên dev set, không đặt một ngưỡng cosine cố định cho mọi model. Điểm reranker không phải xác suất câu trả lời đúng.
- Kiểm tra source ID có tồn tại, trang/quote khớp nguồn; đánh giá thêm câu khẳng định có thực sự được nguồn hỗ trợ. Kiểm tra ID đơn thuần không chứng minh tính đúng.
- Nội dung PDF/DOCX là dữ liệu không đáng tin cậy, không có quyền đổi chỉ thị hệ thống hoặc gọi công cụ. Tách rõ chỉ thị hệ thống và context, giới hạn source ID được phép dùng, escape khi hiển thị. Thêm ca thử tài liệu chứa “bỏ qua hướng dẫn trước đó”, yêu cầu tiết lộ bí mật hoặc chèn citation giả; kiểm tra cả nguồn hợp lệ có lẫn chỉ thị độc hại.
- Câu hỏi chưa đủ bằng chứng trả HTTP 200 với status insufficient_evidence, citations [] và confidence null, cùng thông báo như: “Tài liệu hiện tại chưa cung cấp đủ thông tin để trả lời.” Lỗi API/timeout trả envelope lỗi HTTP 4xx/5xx, không chuyển thành từ chối thiếu bằng chứng.

**Lịch 8 tuần có đầu ra kiểm chứng được vào cuối mỗi tuần.**

| Tuần | A | B | C | Mốc nghiệm thu |
|---|---|---|---|---|
| 1 | Repo, contract/OpenAPI, schema, corpus mẫu, CI và storage | Smoke test model/phần cứng, SearchHit, protocol đánh giá | API chat, wireframe, mock UI, smoke test LLM | Contract được review, 5 tài liệu và 15 câu mẫu, chốt máy/ngân sách |
| 2 | Upload/status/retry, PDF/DOCX chuẩn hóa, fixed chunks | Dense + BM25 bản đầu với index manifest | Generation và UI skeleton theo mock contract | Ba mảng chạy độc lập, output khớp schema |
| 3 | Provenance, lifecycle, staging/publish, xóa an toàn | Dense/BM25, RRF/rerank và context selection | Chat/citation/abstention, nối UI với API | Contract checks và module tests đạt; thử nối E2E sớm nếu sẵn sàng |
| 4 | Tích hợp ingestion → index, retry/cleanup, Compose | Tích hợp search/rerank, kiểm tra version và filter | Hoàn thiện chat/source viewer, kiểm thử toàn luồng | MVP Upload → Index → Search → Answer → Citation; từ chối hoạt động; tag v0.1.0 |
| 5 | Thí nghiệm chunking, kiểm tra provenance/corpus | Runner, embedding/hybrid/reranking trên dev | Chấm generation/citation/abstention | Gold 150–250 câu, mục tiêu 180; kết quả dev vòng đầu |
| 6 | Phân tích lỗi chunking và extraction | So sánh retrieval, hiệu chỉnh gate với C | Thí nghiệm confidence nếu đủ dữ liệu hiệu chỉnh; hoàn thiện đánh giá | Đóng cấu hình/baseline và rubric trước khi mở test; confidence vẫn null nếu chưa đủ điều kiện |
| 7 | Đóng gói, kiểm tra startup và fault/retry | Ablation đã định trước, test đã khóa, báo cáo độ trễ | Kiểm thử luồng, chấm kết quả test, chuẩn bị demo | Báo cáo từng tầng và hệ thống, bản ứng viên; tag v0.9.0 |
| 8 | README cài mới, bàn giao vận hành | Viết phân tích kết quả/giới hạn | Video/kịch bản demo, tích hợp báo cáo | Release v1.0.0, source code, báo cáo và demo |

Phụ thuộc quan trọng: contract/schema → M03/M04 có provenance → M05/M06 → M07 → M08 → M09. Tuần 2–3 dùng mock đúng contract để phát triển độc lập; tuần 4 là mốc tích hợp MVP bắt buộc. Nối E2E cuối tuần 3 là mốc sớm nếu đủ điều kiện, không thay thế kiểm tra tích hợp tuần 4. Nếu trễ, bỏ mục mở rộng và giảm quy mô corpus; vẫn giữ hybrid, reranking, citation và từ chối trong bản cuối.

**GitHub dùng main ổn định và các nhánh ngắn theo issue.**

Tên repo gợi ý: `vietnamese-rag`. Dùng một monorepo để version backend, frontend, schema và experiment cùng nhau. Nhóm 3 người chưa cần một nhánh dài hạn riêng cho mỗi người hay một tầng tích hợp develop. Main chỉ nhận thay đổi đã được review và CI kiểm tra; demo dùng release tag trên main.

| Nhánh dự kiến | Người chính | Nội dung |
|---|---|---|
| main | Cả nhóm qua PR | Bản tích hợp ổn định, nhánh dài hạn duy nhất |
| chore/00-api-contract | A; B/C review | Chốt OpenAPI, schema/lỗi, lifecycle/version và mock examples trước feature |
| chore/01-project-setup | A | Cấu trúc, schema, CI, cấu hình môi trường |
| feat/02-document-upload | A | File storage, API và trạng thái job |
| feat/03-pdf-docx-ingestion | A | PDF, DOCX conversion, provenance |
| feat/04-chunking-strategies | A | Các phương pháp chunking |
| feat/05-dense-retrieval | B | Embedding adapter và Qdrant |
| feat/06-bm25-hybrid | B | BM25, RRF, filter và khử trùng |
| feat/07-reranking | B | Rerank và chọn context |
| feat/08-answer-citations | C | Chat API, LLM và nguồn |
| feat/09-evidence-refusal | C + B | Điều kiện từ chối và kiểm tra bằng chứng |
| feat/10-upload-chat-ui | C | Upload, trạng thái, hỏi đáp |
| feat/11-source-viewer | C | Mở nguồn đúng trang |
| feat/12-document-lifecycle | A + B | Xóa, retry và rebuild index |
| test/13-evaluation-suite | B; A/C cùng đóng góp | Dataset, runner, metric từng tầng, regression và contract checks |
| chore/14-demo-packaging | A | Docker và cách chạy demo |
| docs/15-report-demo | C; A/B cùng đóng góp | README, báo cáo, kịch bản |
| fix/<issue>-<mo-ta> | Người xử lý lỗi | Lỗi phát sinh, tạo khi cần |

Số trong tên nhánh là ví dụ số issue, không phải các nhánh phải tạo ngay. Mỗi nhánh xử lý một issue đủ nhỏ để review trong khoảng 1–3 ngày; nếu một mục lớn thì chia thành nhiều issue/PR. Nhánh thực nghiệm chỉ cần khi thay đổi code; các biến thể model/chunking nên nằm trong file config để dễ tái lập.

Quy trình cho một đầu việc:

```bash
git switch main
git pull --ff-only origin main
git switch -c feat/05-dense-retrieval
# Thực hiện issue, kiểm tra và commit
git push -u origin feat/05-dense-retrieval
# Tạo PR -> review -> CI đạt -> squash merge -> xóa nhánh đã merge
```

Thiết lập GitHub: yêu cầu PR, ít nhất một người khác approve, lint/test/build và contract checks phải đạt; không force-push main; giải quyết conversation trước khi merge. Người thay đổi schema phải có người sử dụng schema review. Kiểm tra OpenAPI hợp lệ, examples khớp schema và response triển khai khớp contract; thay đổi phá vỡ tương thích phải cập nhật phiên bản và client có kế hoạch. CI thông thường dùng fixture nhỏ và LLM mock; benchmark model thật chạy riêng để tránh khóa mọi PR vào API/GPU. GitHub hỗ trợ required reviews/status checks trên protected branches; phạm vi khả dụng tùy gói và loại repo. Xem [GitHub protected branches](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches).

Mỗi issue ghi mục tiêu, người phụ trách, dependency và acceptance criteria. Mỗi PR ghi thay đổi, cách kiểm chứng và ảnh giao diện nếu có. Board dùng Backlog → Ready → In progress → Review → Done. Giới hạn mỗi người một đầu việc chính đang triển khai; phản hồi PR trong một ngày làm việc; demo cuối tuần và tích hợp sớm trong tuần.

**Cấu trúc repo dự kiến bám theo module, không chia thư mục theo tên thành viên.**

```text
vietnamese-rag/
  backend/
    app/
      api/                 # /api/v1/documents, search, chat, health
      schemas/             # Document, Chunk, SearchHit, Answer, Citation
      ingestion/           # loaders, converter, normalizer
      chunking/            # fixed, recursive, heading-aware
      indexing/            # embedding, dense/BM25 build, versioning
      retrieval/           # dense, BM25, fusion, reranker
      generation/          # prompts, LLM adapter, citations, refusal
      storage/             # files, metadata, active versions
      jobs/                # worker và trạng thái xử lý
      core/                # config, logging
    tests/
    pyproject.toml
  frontend/
    src/
      components/
      pages/
      services/            # API client
    package.json
  evaluation/
    datasets/              # gold đã được phép chia sẻ
    runners/
    metrics/
    results/               # bảng kết quả nhỏ, không lưu secrets
  experiments/
    configs/               # chunking, model, retriever, prompt version
  data/
    samples/               # dữ liệu mẫu có quyền chia sẻ
    raw/                   # gitignore
    processed/             # gitignore
  docs/
    architecture.md
    api-contract.md
    openapi.yaml
    technical-rules.md
    evaluation-protocol.md
    report.md
  .github/
    workflows/ci.yml
    pull_request_template.md
  compose.yaml
  .env.example
  .gitignore
  README.md
```

Không commit API key, .env thật, model weights, vector index, cache hoặc tài liệu riêng tư. Lưu model ID/revision, index/config version, corpus manifest/hash và script dựng lại để người khác tái lập. Khóa dependency và ghi phần cứng trong kết quả benchmark.

**Phần nghiên cứu cần dữ liệu và quy tắc đánh giá trước khi tối ưu.**

Chuẩn bị 150–250 câu; mục tiêu kế hoạch là 180 câu: 120 câu có đáp án (trực tiếp, diễn đạt lại, thuật ngữ và kết hợp nhiều đoạn) và 60 câu không đủ bằng chứng (ngoài phạm vi hoặc cùng chủ đề nhưng thiếu thông tin cần hỏi). Mỗi người soạn 60 câu và kiểm tra chéo. Chia 90 dev và 90 test, giữ tỷ lệ các loại gần tương đương; gom paraphrase cùng họ câu hỏi vào một tập, ưu tiên nhóm theo nguồn/chủ đề để hạn chế rò rỉ. Toàn bộ corpus tra cứu vẫn được index; câu hỏi/nhãn test không được dùng để chọn tham số. Chốt split, rubric và baseline trước khi xem kết quả test.

Gold lưu `question`, `answerable`, `reference_answer`, danh sách `document_id + document_version + page_number + quote + source_span`; câu không có đáp án ghi lý do. Không chỉ dùng chunk_id làm gold vì chunk thay đổi giữa các phương pháp. Nếu câu hỏi cần nhiều bằng chứng, đánh dấu tất cả span cần thiết và đo khả năng tìm đủ bằng chứng, không chỉ trúng một đoạn. Các nhóm bằng chứng thay thế hợp lệ phải được ghi rõ để không coi một nguồn tương đương là lỗi.

Tách kết quả retrieval, reranking và generation. Ghi ứng viên trước/sau rerank; so sánh LLM trên context thực tế với LLM được cấp gold evidence để phân biệt lỗi không tìm được nguồn, xếp hạng sai, đọc sai bằng chứng và citation không hỗ trợ câu trả lời. Không gộp toàn bộ thành một chỉ số chất lượng.

| Giai đoạn | Biến thay đổi | Giữ cố định | Người thực hiện |
|---|---|---|---|
| E1 | Fixed token, recursive, heading-aware chunking | E5, dense retrieval, giới hạn kích thước tương đương | A |
| E2 | E5-small và BGE-M3 dense | Chunking chọn từ E1, cùng corpus và query | B |
| E3 | BM25; dense; hybrid RRF; hybrid + rerank | Chunking, embedding, corpus, top-k được định trước | B |
| E4 | Chất lượng trả lời và từ chối với cấu hình cuối/baseline | Cùng LLM, prompt, context budget, tập câu hỏi | C |
| E5 | Confidence đã hiệu chỉnh so với baseline, nếu đủ điều kiện dữ liệu | Định nghĩa nhãn, protocol calibration, model/prompt và bộ test giữ kín | B + C |

Đây là thí nghiệm tuần tự để phù hợp thời gian nhóm, không phải khảo sát đầy đủ mọi tổ hợp hay tương tác. Báo cáo phải nêu giới hạn đó. Khởi đầu chunk khoảng 300–400 token, overlap 50–80 token; kiểm tra tokenizer của cả embedding và reranker để tránh truncation. Chỉ đổi thêm kích thước chunk khi còn thời gian sau các so sánh chính.

Tối ưu trên dev; định trước baseline và cấu hình cuối rồi mới chạy test. Nếu sửa logic sau khi xem test, ghi rõ phiên bản và không coi kết quả chạy lại là một đánh giá độc lập chưa từng được xem.

Nếu nghiên cứu confidence, dành dữ liệu hiệu chỉnh/đánh giá độc lập hoặc cross-validation bên trong dev theo protocol; không fit calibrator trên test. Với bộ 180 câu, có thể chưa đủ bằng chứng để công bố calibration đáng tin cậy. Khi chưa đạt điều kiện, giữ confidence null, ghi giới hạn và ưu tiên benchmark retrieval/generation/abstention.

| Metric | Cách hiểu và phạm vi |
|---|---|
| Evidence Recall@5/10 | Tỷ lệ gold evidence tìm được trong top-k trên câu có đáp án; quy tắc khớp span cố định, không lệ thuộc chunk ID |
| MRR@10 | Vị trí bằng chứng liên quan đầu tiên trong top 10; dùng cùng quy tắc relevance |
| Độ đúng câu trả lời | Người chấm so với đáp án tham chiếu; có thể dùng mức đúng/đúng một phần/sai |
| Citation precision | Tỷ lệ liên kết claim–citation mà đoạn nguồn thực sự hỗ trợ claim |
| Citation coverage | Tỷ lệ khẳng định cần dẫn chứng được dẫn đúng nguồn |
| Abstention precision | Số câu thiếu bằng chứng bị từ chối / tổng câu bị từ chối; lớp dương là insufficient_evidence |
| Abstention recall | Số câu thiếu bằng chứng bị từ chối / tổng câu thiếu bằng chứng; cùng định nghĩa lớp dương |
| Từ chối nhầm | Số câu bị từ chối / tổng câu có đủ bằng chứng |
| Lỗi vận hành | Báo riêng số/tỷ lệ timeout và lỗi HTTP; không tính chúng là từ chối và không âm thầm loại khỏi mẫu |
| Hiệu năng/chi phí | Latency p50/p95, thời gian index, RAM/VRAM, token và chi phí theo cấu hình máy/model |

Nhóm đánh giá chéo bằng rubric chung; bất đồng được đối chiếu lại tài liệu. LLM-as-judge nếu dùng chỉ hỗ trợ, không thay toàn bộ đánh giá thủ công. Báo cáo cả số lượng mẫu và tỷ lệ, phân loại lỗi do extraction, chunking, retrieval, reranking, generation hay citation. Mẫu số bằng 0 phải trả metric null kèm lý do. Benchmark Recall@5 và MRR@10 phải lưu ít nhất top 10; mỗi run lưu index/corpus/config/model/prompt revisions và trạng thái thu hồi tài liệu để nhận biết dữ liệu đã thay đổi.

**Điều kiện nghiệm thu MVP cần được kiểm chứng, không phải cam kết chất lượng trước benchmark.**

| Hạng mục | Tiêu chí đề xuất |
|---|---|
| API contract | Endpoint, schema request/response/error và examples thống nhất; triển khai vượt qua contract checks |
| Upload PDF/DOCX | Xử lý thành công file mẫu hợp lệ; file lỗi/scan chưa hỗ trợ báo đúng trạng thái |
| Provenance | 100% chunk được đưa vào index có nguồn, phiên bản và vị trí trang hợp lệ |
| Retrieval | Đo Recall@5 và MRR@10 trên gold đã khóa; có baseline BM25/dense/hybrid |
| Reranking | Có so sánh trước/sau reranking trên cùng tập ứng viên và corpus |
| Citation | 100% citation ánh xạ về nguồn hợp lệ; đo riêng việc nguồn có thực sự hỗ trợ nội dung |
| Abstention | Đo precision/recall với lớp dương là câu thiếu bằng chứng; báo cả từ chối nhầm và lỗi vận hành |
| Confidence | null khi chưa có estimator được hiệu chỉnh và đánh giá; kết quả ví dụ không được ghi thành số đo |
| Lifecycle | Xóa chặn truy xuất ngay, retry không tạo lặp/hồi sinh; dọn mọi generation và cả bốn nơi lưu dữ liệu |
| Reproducibility | Chạy lại bằng cùng config, corpus/index/model/prompt versions; ghi nhận thay đổi do thu hồi dữ liệu |
| Prompt injection | Có ca kiểm thử chỉ thị độc hại trong PDF/DOCX; nguồn được coi là dữ liệu không đáng tin cậy |
| Deployment | Khởi chạy bằng Docker Compose trên môi trường sạch theo README, có .env.example và dữ liệu demo hợp lệ |

Không đặt ngưỡng Recall/citation/abstention như một kết quả đã đảm bảo. Nếu nhóm thống nhất thêm mục tiêu số, phải chốt từ baseline/dev trước khi mở test và báo cáo trung thực khi chưa đạt. Chốt mục tiêu latency sau đo tuần 1; công bố p50/p95 cùng phần cứng và mức đồng thời. Bàn giao code, release v1.0.0, corpus manifest, dataset đánh giá, cấu hình, bảng kết quả, báo cáo và video/kịch bản demo.

**Ba ngày đầu nên tạo ngay cơ sở để cả nhóm cùng làm.**

1. Ngày 1: chọn chuyên ngành, xác nhận thời lượng/phần cứng/ngân sách; tạo repo/board và issue contract/schema, dữ liệu mẫu, retrieval mock, UI mock.
2. Ngày 2: review và chốt API contract/OpenAPI, lỗi/lifecycle/version cùng ví dụ; A đưa 5 file mẫu có trang, B đưa SearchHit mẫu, C rà payload UI; mỗi người viết 5 câu gold đầu tiên.
3. Ngày 3: xác nhận contract không còn mâu thuẫn, chạy smoke test model/phần cứng, thống nhất rubric/dataset split; merge contract trước khi mở các nhánh triển khai tuần 2.
