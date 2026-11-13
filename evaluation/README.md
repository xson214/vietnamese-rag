**Đánh giá retrieval và abstention bằng một generation đã ghim.**

Chạy từ thư mục gốc repository, với backend đang hoạt động và một index đã publish:

```powershell
python -m evaluation.run --dataset path/to/reviewed-gold.json --index-version idx_... --output evaluation/results/run-001
```

Mỗi câu gọi `/search` với top_k=10 (đo Evidence Recall@5 và MRR@10) và `/chat` với top_k=5 mặc định. Dùng `--retrieval-config experiments/configs/dense.json` để chọn cấu hình. Tệp config chứa object các cờ `dense`, `bm25`, `reranking`, `top_k`; runner luôn ép top_k=10 riêng cho search. Tùy endpoint dùng `--base-url http://localhost:8000/api/v1`. Thư mục output phải chưa tồn tại để không ghi đè run cũ.

Gold JSON có `dataset_version`, `fixture_only`, `questions`. Mỗi câu có `question_id`, `question`, `answerable`, phạm vi `document_ids` nếu cần và `evidence_sets`. Mỗi set là tập bằng chứng đầy đủ (AND các span), các set thay thế nhau (OR). Span có document_id, document_version, page_number, start_offset, end_offset, quote; Unicode code point offset theo text chuẩn trang, khoảng [start,end). Các metadata review/hash/split bổ sung theo [protocol](../docs/evaluation-protocol.md). Runner kiểm tra cấu trúc cơ bản, người gán nhãn phải kiểm chứng quote và offset thật trên corpus.

Hai câu trong `datasets/demo_gold.json` **chỉ là fixture minh họa**. Chúng chưa phải 180 câu gold được người dùng kiểm tra. Không trình bày kết quả chạy fixture thành chất lượng nghiên cứu. Dùng `--allow-fixtures` mới cho phép chạy fixture; sau khi upload PDF chứa `demo_corpus.txt`, đối chiếu text/offset thực và tạo `document-map.json`, ví dụ `{"demo-document":"doc_..."}`, rồi thêm `--document-map document-map.json`.

Output gồm manifest, predictions đầy đủ và summary. Recall dùng hợp các khoảng nguồn, không dựa chunk ID; MRR dùng hit đầu tiên tự chứa trọn một gold span. Lỗi retrieval tính 0 trên các câu answerable, lỗi chat được giữ riêng trong confusion counts. `recall_all` của abstention đưa lỗi vào mẫu số. Mẫu số bằng 0 trả null. Các metric độ đúng câu trả lời/citation ngữ nghĩa vẫn cần chấm theo rubric; runner không tự tuyên bố các metric này đạt.

Thêm `--run-metadata run-metadata.json` để lưu LLM ID/revision, prompt hash, dependency lock hash và phần cứng cụ thể theo protocol. Không bỏ các thông tin này khi công bố benchmark; API trace chỉ nhận dạng generation/corpus/embedding/chunking. Không đặt API key trong metadata. Summary có p50/p95 thời gian search/chat gồm cả các request lỗi; raw predictions giữ thời gian từng request để phân tích riêng.

Mỗi response phải có đúng index_version, cùng corpus_snapshot_id/model/chunking. Generation thu hồi hoặc đổi corpus làm run invalid (exit code 2), không fallback hoặc ghép kết quả. Có probe cuối để phát hiện generation bị thu hồi. Index vẫn có thể bị xóa sau khi run kết thúc, do đó manifest xác nhận thời điểm run, không bảo đảm artifact tồn tại vĩnh viễn. LLM API có thể không xác định hoàn toàn dù temperature=0.

API không trả secrets cho runner. Bản output có thể chứa quote/câu trả lời, do đó xem như dữ liệu thuộc corpus và đưa vào chính sách lưu trữ/xóa của nhóm. Không commit kết quả chứa tài liệu riêng tư.
