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
