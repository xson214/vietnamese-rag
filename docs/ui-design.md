**Thiết kế giao diện Vietnamese RAG bằng ui-ux-pro-max — 13/11/2026.**

Skill sử dụng: `.agents/skills/ui-ux-pro-max/SKILL.md` do người dùng cung cấp trong workspace. Phạm vi thay đổi là frontend React/TypeScript, không đổi API hay cách lưu API key.

Đã chạy CLI thiết kế tổng thể với hai truy vấn `AI knowledge workspace document chat` và `document management SaaS dashboard`, dials variance 4, motion 2, density 6. Kết quả có hướng Minimalism/Swiss và bảng màu document-grey/scan-blue phù hợp; phần bố cục trả Hero + Features + CTA ở cả hai lần không phù hợp ứng dụng làm việc, nên không dùng/persist bố cục đó. Bố cục workspace dưới đây là quyết định thiết kế theo cấu trúc sản phẩm hiện có và hướng dẫn UX chung. Có tìm kiếm riêng `keyboard focus modal` ở domain UX và `forms state accessibility` cho stack React.

| Thành phần | Quyết định |
|---|---|
| Phong cách | Workspace sáng, nền xám xanh nhẹ, bề mặt trắng, chia nhóm bằng khoảng cách/border |
| Màu chính | #245BD6; chữ #17243B; chữ phụ #566780; nền #F5F7FB |
| Chữ | Giữ Be Vietnam Pro để hiển thị tiếng Việt; heading 32–48px, nội dung trả lời 15px desktop/16px mobile |
| Sidebar | Danh sách tài liệu, upload, tìm tên file và phạm vi tài liệu; mobile mở bằng nút Tài liệu |
| Welcome | Tiêu đề ngắn, ba bước làm việc, ba thẻ câu hỏi gợi ý |
| Hội thoại | Answer card dễ đọc, nguồn dạng thẻ, trace thu gọn; composer luôn ở đáy vùng làm việc |
| Cài đặt | Native dialog ở bên phải, không đẩy hội thoại xuống; nhóm generation và retrieval riêng |
| Nguồn | Native dialog xem PDF; quote và link nguồn vẫn giữ hành vi hiện có |
| Keyboard | Skip link, focus ring, native modal focus trap/Escape/khôi phục focus; drawer mobile có focus trap và nền inert |
| Motion | Chuyển màu/viền nhẹ; không thêm GSAP; tắt animation khi reduced-motion |
| Responsive | Mobile dưới768, bố cục gọn dưới1150 và desktop rộng1600; wrap ID/URL và form một cột ở mobile |

Các màu trạng thái luôn đi cùng chữ. Dùng SVG icon sẵn có cùng một nét vẽ, không thêm emoji hoặc package UI mới. Cấu hình key vẫn chỉ giữ trong RAM; không thêm localStorage/sessionStorage. Chưa thêm theme tối vì cần kiểm tra riêng về contrast và trạng thái thay vì đảo màu tự động.

Xác minh: TypeScript/Vite production build đạt; git diff --check đạt. Kiểm tra static CSS gồm responsive, focus states, reduced-motion và wrap nội dung dài. Kiểm tra hình ảnh trực tiếp chưa hoàn thành: browser connector không khả dụng, native Brave có đúng trang RAG nhưng cửa sổ minimized và getApp không khôi phục được sau retry. Không tuyên bố đạt WCAG hoặc đã kiểm chứng ảnh ở mọi viewport.

Khi kiểm tra trực tiếp trên browser, cần thử 375/768/1440px và landscape: mở drawer thư viện, tab quanh các controls, Escape đóng/khôi phục focus; mở Cấu hình/API key/model; mở citation/PDF; thử lỗi và trạng thái chờ; thử font lớn và reduced-motion. Build không thay thế các phép kiểm tra trực quan này.

Điều chỉnh vùng chọn tài liệu: sidebar rộng 380px trên desktop, 420px ở màn hình từ 1600px, 340px ở tablet; drawer mobile dùng gần hết chiều ngang (tối đa 420px). Gộp tải tệp/chụp ảnh cùng hàng, thu gọn hướng dẫn OCR bằng disclosure để nhường chiều cao cho danh sách; danh sách tối thiểu 200px và sidebar có cuộn dự phòng ở màn hình thấp. Tên file xuống dòng đầy đủ, chữ lớn hơn, không cắt bằng ellipsis. Có số tài liệu đã chọn, chọn tất cả/kết quả lọc, bỏ chọn và xóa bộ lọc. Khi đang tìm toàn bộ tài liệu, bỏ chọn một file giữ các file còn lại được chọn.

Nút chữ “Đọc lại tài liệu” cho PDF/ảnh gọi API reprocess thành phiên bản mới. Giữ lựa chọn theo document_id khi tài liệu đang xử lý; phạm vi chọn riêng chỉ hỏi được khi các tài liệu đã chọn sẵn sàng, và có thông báo đang chờ. Có thể bỏ chọn một tài liệu đang xử lý hoặc thất bại. Nút mở/xóa/thử lại đều có accessible name chứa tên tài liệu. Các thay đổi này đã qua TypeScript/Vite production build và diff whitespace check; cần kiểm tra trực quan trong browser khi connector khả dụng.

Xác minh bổ sung ngày 13/11/2026: đã kiểm tra trực tiếp bằng Computer Use trên Brave desktop 1920px và DevTools responsive 375px. Tên file dài xuống dòng, danh sách đủ rộng, lọc tên/bỏ chọn/chọn kết quả hoạt động; drawer mobile gần toàn chiều ngang, nội dung không tràn ngang trong các màn hình đã xem. Câu hỏi thực tế trên tài liệu OCR đã xử lý lại hiển thị câu trả lời và thẻ nguồn trang 6. Đã đóng DevTools, khôi phục desktop. Kiểm tra này không thay thế kiểm toán WCAG hoặc thử toàn bộ breakpoint/trình duyệt.
