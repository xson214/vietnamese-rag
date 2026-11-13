**Khắc phục LLM_BAD_RESPONSE khi dùng Gemini — 13/11/2026.**

Thông báo người dùng nhận được là “LLM trả lời không đúng schema.” Từ đường đi trong code có thể xác định: provider đã trả response thành công, nội dung đã parse được thành JSON, nhưng object không vượt qua hợp đồng status/answer/source_ids. Lỗi này khác key sai hoặc endpoint không kết nối được. Request cũ không lưu raw response và key được giữ riêng trong tab, nên chưa xác định được chính xác trường nào trong phản hồi thực tế gây lỗi.

Hai điểm ở implementation cũ góp phần gây lỗi:

- `response_format: json_object` chỉ yêu cầu JSON hợp lệ, không ràng buộc ba trường của hợp đồng.
- Ví dụ prompt dùng `"answered"|"insufficient_evidence"` để diễn tả lựa chọn, nhưng đó không phải JSON hợp lệ; validator lại yêu cầu chính xác ba trường và không chấp nhận metadata thêm.

Bản sửa gửi JSON Schema có status enum, answer string, source_ids array với enum các ID context hiện tại; sửa prompt thành hai ví dụ JSON hợp lệ. Google công bố hỗ trợ structured output qua lớp OpenAI-compatible: [tài liệu chính thức](https://ai.google.dev/gemini-api/docs/openai#structured-output).

Adapter xử lý code fence bao trọn JSON, content dạng text parts hoặc parsed object, bỏ metadata model tự sinh và chuẩn hóa danh sách nguồn. Chỉ khôi phục source_ids từ marker đã có trong answer khi status answered được model cung cấp rõ ràng. Không suy đoán answer/status, không thêm marker và không tin filename/page/quote do model tự sinh. Mọi ID vẫn kiểm tra trong context; citations cuối do backend resolve.

Nếu JSON/schema/citation chưa đạt, tạo lại đúng một lần từ bằng chứng gốc; không đưa raw output lỗi vào log, API error hoặc prompt repair. Nếu provider báo rõ không hỗ trợ json_schema thì chỉ thương lượng xuống json_object một lần, vẫn giữ validator. Tối đa ba HTTP calls (một negotiation fail và hai completion attempts), cùng timeout chung; có thể phát sinh thêm token cho completion thứ hai. Key/quota/transport errors không retry theo logic repair. Refusal/content_filter và response length truncation có mã lỗi riêng, không repair.

Trace thành công có generation_attempts, response_format, response_repaired và prompt_version. Lỗi thiếu trường chỉ nêu tên trường cố định, không echo giá trị provider hoặc key.

Tests dùng HTTP mocks để tái hiện các định dạng khác nhau và kiểm tra unknown-source rejection, repair một lần, negotiation, timeout chung, auth/quota/refusal và không lộ key. Chưa xác minh lại với Gemini thật vì key không được lưu ở server. Sau restart backend, người dùng có thể gửi lại câu hỏi trong tab đã cấu hình Gemini; không cần upload lại hay reindex tài liệu.

Xác minh bản sửa: toàn bộ 100 tests và 2 subtests đạt; Ruff và OpenAPI drift check đạt. Có ca tích hợp gọi /chat với generation_config Gemini riêng cho tab, model trả sai schema lần đầu và JSON fenced hợp lệ lần hai; API trả answered, citation do backend resolve và không lộ key. Các provider responses trong tests là mock, không phải phép đo Gemini thật. Backend local cổng 8000 đã được khởi động lại với code mới.
