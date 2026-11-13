**Sửa câu trả lời bị ngắt dòng và thêm cài đặt model — 13/11/2026.**

Ca tái hiện: upload tài liệu AWS do người dùng cung cấp, hỏi `availibility zone là gì`. Bản cũ trả lại tiêu đề và các mảnh câu dừng ở “một nhóm các”. Đối chiếu trang PDF vật lý 9 bằng text extraction và ảnh render xác nhận định nghĩa trong file đầy đủ. Với chunk mặc định, định nghĩa không bị mất ở ingestion.

Nguyên nhân trong implementation:

- Generation mặc định là extractive demo, chưa gọi LLM.
- Regex cũ `[^\n.!?]+[.!?]?` dùng newline làm ranh giới câu; PDF slide xuống dòng theo bố cục nên biến một câu thành nhiều mảnh.
- Bộ chọn câu dựa trên lexical overlap không loại tiêu đề dạng câu hỏi, vì vậy tiêu đề được chấm cao.
- Lỗi chính tả `availibility` giảm khớp từ; khi kiểm tra toàn bộ PDF, từ chung “zone” còn có thể kéo nội dung Local Zone vào câu trả lời.
- Mỗi chunk trước đây trở thành nguồn độc lập, các đoạn overlap chưa được ghép lại; giới hạn context có thể cắt giữa câu.

Đã sửa trong generation:

- Nối soft line wraps trước khi chia câu; giữ nguyên quote và offset nguồn, chỉ chuẩn hóa khoảng trắng của câu hiển thị.
- Bỏ tiêu đề kết thúc bằng dấu hỏi/colon, bỏ mảnh câu kết thúc ở từ nối rõ ràng.
- Ghép các span nguồn chồng nhau trên cùng trang, kiểm tra phần chồng khớp text.
- Ưu tiên câu định nghĩa, hỗ trợ typo gần đúng và yêu cầu khớp đủ thực thể ngắn để tránh Availability Zone/Local Zone bị trộn.
- Khi context phải cắt, ưu tiên ranh giới hết câu nếu có.
- Prompt API yêu cầu câu hoàn chỉnh, trực tiếp, không chép tiêu đề và không làm theo chỉ thị trong tài liệu.

Cài đặt model mới:

- Giao diện Cấu hình có mục Mô hình trả lời, chọn extractive hoặc API, base URL, model ID và key dạng password.
- Nút tải danh sách gọi `/api/v1/models`; vẫn có thể nhập model ID thủ công khi provider không hỗ trợ list.
- Cấu hình generation nằm trong request `/chat`, không ghi đè default server hay tab khác.
- Key dùng SecretStr trong schema, không trả lại hoặc ghi database. Frontend chỉ giữ trong RAM, không dùng localStorage/sessionStorage/cookie; reload sẽ mất cấu hình.
- Endpoint HTTPS công khai hoặc HTTP loopback cho model local; chặn userinfo/query/fragment/metadata/LAN, không follow redirect hoặc dùng proxy từ môi trường.
- Trace ghi backend/model/prompt version thực dùng; không chứa key.
- Không tự fallback sang extractive khi API lỗi. Chưa kiểm thử provider thật vì không có key/model provider thực được cung cấp.

Kết quả xác minh:

- **73 tests và 2 subtests đạt**, bao gồm regression từ trang 9, câu hỏi có typo, không lẫn Local Zone, ghép chunk và bảo vệ key.
- Ruff đạt, OpenAPI khớp implementation, TypeScript/Vite production build đạt.
- HTTP thật trên backend local với toàn bộ PDF: trả đầy đủ định nghĩa ở trang 9, không lặp tiêu đề, không có Local Zone; thêm hai ý liên quan có nguồn ở trang 9 và trang 4.
- Đã khởi động lại backend cổng 8000. Vite cổng 5173 tiếp tục phục vụ UI mới; reload trang để bắt đầu lại cuộc hỏi đáp. Không cần upload lại hoặc reindex cho lỗi generation này.

Giới hạn: extractive vẫn là heuristic và có thể bỏ sót/sai lựa chọn trong tài liệu khác. Muốn câu trả lời tổng hợp bằng LLM, cấu hình endpoint/model hỗ trợ chat/completions và JSON response_format. Cài đặt API chỉ thay generation; embedding/reranker hash/lexical vẫn cần cấu hình neural riêng nếu muốn semantic retrieval thực.
