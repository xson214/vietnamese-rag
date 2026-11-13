**Trạng thái bàn giao MVP ngày 13/11/2026.**

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
