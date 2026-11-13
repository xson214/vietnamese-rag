**Trạng thái bàn giao MVP ngày 13/11/2026.**

Cập nhật embedding thật: ứng dụng native và Compose mặc định Sentence Transformers `intfloat/multilingual-e5-small` tại commit `614241f622f53c4eeff9890bdc4f31cfecc418b3`, vector L2 384 chiều. Đã cài PyTorch CPU/Sentence Transformers, chạy inference và smoke dense-only liên ngôn ngữ, dựng generation mới từ **8 tài liệu / 432 chunks** và khởi động lại API. HTTP dense-only câu hỏi Availability Zone tìm trang 9; câu hỏi PDF liều dùng vẫn answered có nguồn trang 6. Index cũ giữ nguyên. 169 tests + 2 subtests đạt; pip check, Ruff, OpenAPI và Compose config đạt. Reranker hiện vẫn lexical; đây chưa phải benchmark chất lượng trên gold. Model cache/nguồn người dùng không đưa vào Git. Xem `scripts/setup_embedding.py`, `experiments/configs/multilingual-e5.json`, `backend/requirements-neural.lock` và README cho setup/reindex.

Cập nhật sửa PDF scan và không gian làm việc: nhận biết lớp OCR vô hình bị hỏng, OCR lại từ ảnh; endpoint reprocess tạo document_version mới và giữ nguồn/index cũ; câu hỏi liều cho trẻ theo khoảng tuổi trả điều kiện sử dụng có trích dẫn và yêu cầu bổ sung dữ kiện. Với PDF người dùng cung cấp, smoke HTTP thật sau reprocess trả answered, nguồn trang vật lý 6, không suy ra liều cụ thể. Giao diện đã kiểm tra trực tiếp trên Brave desktop và chế độ 375px: lọc tên, chọn riêng tài liệu, hỏi đáp và drawer mobile hoạt động. **165 tests + 2 subtests đạt**, Ruff/OpenAPI/frontend build đạt; có test phục hồi bản sao chưa commit khi đọc lại. Gemini thật chưa được gọi trong đợt kiểm tra này.

Cập nhật OCR: đã hỗ trợ ảnh JPG/PNG/WebP và trang PDF scan; Tesseract cục bộ vie+eng chạy thật trên Windows qua binding trong subprocess. 147 tests và 2 subtests đạt, frontend build/OpenAPI/Compose config đạt. Smoke HTTP thực với ảnh tiếng Việt và PDF scan trả lời và dẫn nguồn trang 1. [Thiết kế OCR](ocr-engine.md) và [README](../README.md) có setup, giới hạn chữ viết tay và cách dùng. Các mốc/giới hạn “chưa OCR” ở bảng bàn giao ban đầu bên dưới là lịch sử trước bản bổ sung này.

Cập nhật tiếp theo cùng ngày: đã sửa generation cho slide PDF xuống dòng và thêm cài đặt model/API key riêng từng tab. Bộ kiểm thử hiện đạt 73 tests và 2 subtests. Xem [phân tích lỗi và xác minh](fix-az-and-model-settings.md). Các số 54 bên dưới ghi lại mốc bàn giao MVP ban đầu.

Cập nhật tương thích Gemini sau đó: structured JSON Schema, chuẩn hóa định dạng và repair hữu hạn; hiện toàn bộ 100 tests và 2 subtests đạt. Xem [khắc phục LLM_BAD_RESPONSE](fix-gemini-response-schema.md). Các số 73 ở đoạn trên là mốc trước bản sửa này.

Code được triển khai từ [kế hoạch](../KE_HOACH_DU_AN.md), với [API contract](api-contract.md) và [OpenAPI sinh từ code](openapi.yaml). Repo Git cục bộ đã khởi tạo nhánh main, chưa có commit hoặc remote GitHub. Không chứa API key hoặc tài liệu của người dùng.

| Phần | Đã thực hiện | Bằng chứng/giới hạn |
|---|---|---|
| API | 10 operations dưới /api/v1, schema strict, envelope lỗi/request ID | Tests + OpenAPI drift check |
| Ingestion | PDF text, DOCX qua LibreOffice, canonical PDF, NFC/LF, Unicode offsets | PDF tiếng Việt chạy HTTP thật; DOCX happy-path được mock converter và missing-converter được kiểm thử, chưa chạy LibreOffice thật |
| Lifecycle | SQLite job bền vững, retry/idempotency, single writer, tombstone, cleanup/revocation | Tests delete giữa build/chat, cleanup lỗi/retry và restart |
| Retrieval | 3 chunking, dense, BM25, RRF, rerank, document filter, immutable generation | Offline chạy thật; neural adapter chưa tải/chạy model |
| Qdrant | REST collection/points/query/filter/cleanup, namespace theo generation | 8 tests HTTP mock, chưa chạy Qdrant server thật |
| Generation | Extractive demo và API model tương thích chat/completions, backend citation, confidence null | Extractive chạy HTTP thật; API provider tests dùng mock |
| UI | Upload/status/retry/delete, scope, chat, config, source viewer, demo label | TypeScript/Vite build thành công, HTTP trang trả200; chưa xác nhận visual vì browser connector không khả dụng |
| Evaluation | Gold schema/fixture, runner pin generation, recall/MRR/abstention/errors/latency | Smoke run 2 câu fixture hợp lệ; chưa có 180 câu gold reviewed hoặc benchmark nghiên cứu |
| Deploy/CI | Compose, Dockerfiles, LibreOffice image, GitHub Actions | Compose config hợp lệ; Docker Engine hiện chưa chạy nên chưa build/run container |

Kiểm tra cuối:

- `python -m pytest -c pyproject.toml -q`: **54 passed, 2 subtests passed**; một cảnh báo deprecation từ Starlette TestClient dùng httpx, không có test thất bại.
- `python -m ruff check backend evaluation scripts`: đạt.
- `python scripts/export_openapi.py --check`: contract khớp implementation.
- `npm --prefix frontend run build`: TypeScript và Vite đạt.
- `docker compose config --quiet`: đạt.
- `scripts/smoke.py`: upload PDF tiếng Việt → index → chat → mở PDF nguồn; confidence null.
- `evaluation.run` trên hai fixture: run hợp lệ, không có retrieval/chat error. Các tỷ lệ trên fixture không dùng làm kết quả nghiên cứu.
- `app.reindex`: tạo generation kế tiếp khi backend đã dừng; khởi động backend trở lại và giữ dữ liệu cũ.

Các địa chỉ trong phiên hiện tại: UI http://127.0.0.1:5173 và API http://127.0.0.1:8000/docs. Tiến trình có thể dừng khi đóng môi trường; [README](../README.md) có lệnh chạy lại, cấu hình neural/LLM và benchmark.

Việc tiếp theo cần môi trường/dữ liệu thật: bật Docker Engine, thử DOCX và Qdrant thực; cài model neural trên phần cứng mục tiêu; cấu hình model API nếu cần sinh tổng hợp; kiểm tra giao diện trên browser; soạn/review gold và chạy thí nghiệm có kiểm soát. Confidence vẫn null cho đến khi có calibration được đánh giá độc lập.
