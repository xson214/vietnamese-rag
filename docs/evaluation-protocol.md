**Quy trình đánh giá Vietnamese RAG trước khi triển khai ứng dụng.**

Tài liệu này quy định cách xây bộ gold, chạy thí nghiệm và nghiệm thu chất lượng. Đây là thiết kế đánh giá; chưa có dataset đã gán nhãn hoặc kết quả benchmark. B chủ trì bộ chạy và retrieval, A phụ trách provenance/chunking, C phụ trách generation/citation; cả ba cùng viết câu hỏi và kiểm tra chéo.

**Bộ gold ban đầu nằm trong khoảng 150–250 câu; kế hoạch làm việc dùng mục tiêu 180 câu.**

| Nhóm câu hỏi | Số dự kiến | Nội dung |
|---|---:|---|
| Có đáp án, một bằng chứng chính | 80 | Trực tiếp, diễn đạt lại, thuật ngữ, điều kiện hoặc con số được ghi rõ |
| Có đáp án, cần nhiều bằng chứng | 40 | Tổng hợp nhiều đoạn/trang/tài liệu; có danh sách các phần bắt buộc phải tìm được |
| Không đủ bằng chứng | 60 | Ngoài phạm vi, cùng chủ đề nhưng thiếu thông tin, tiền đề sai, hỏi dữ kiện không được tài liệu xác nhận |
| Tổng | 180 | Mỗi người soạn 60 câu, người khác đối chiếu tài liệu |

Không dùng câu chỉ khó diễn đạt để gán nhãn không thể trả lời. Nhãn `answerable` được xác định theo corpus và phạm vi `document_ids` của câu hỏi, không dựa vào việc hệ thống hiện tại có tìm được hay không. Người gán nhãn kiểm tra các tài liệu liên quan và ghi lý do cho câu thiếu bằng chứng; nếu phát hiện nguồn trả lời sau này thì sửa dataset version và chạy lại các cấu hình cần so sánh.

Chia dự kiến 90 dev và 90 test. Mỗi tập gồm khoảng 60 câu có đáp án (40 đơn, 20 nhiều bằng chứng) và 30 câu thiếu bằng chứng. Gom mọi paraphrase hoặc câu gần trùng vào cùng `question_family_id`; ưu tiên nhóm theo nguồn/chủ đề khi thực tế cho phép. Nếu tỷ lệ số lượng xung đột với ràng buộc nhóm, giữ nhóm nguyên vẹn và công bố tỷ lệ thực tế. Không dùng chia ngẫu nhiên từng câu làm rò rỉ paraphrase.

Toàn bộ tài liệu cần tra cứu được phép nằm trong corpus đã index. Điều cần giữ kín trong quá trình chọn cấu hình là câu hỏi, đáp án và gold evidence test. Bộ 15 câu mẫu tuần 1 thuộc dev; không dùng chúng như test cuối. Nhóm chỉ mở test sau khi đã khóa cấu hình, prompt, rubric và baseline. Người quản lý test giữ nhãn khỏi vòng tối ưu; repo public chỉ chứa fixture dev hoặc phát hành gold test sau khi chốt đánh giá.

**Gold lưu bằng chứng theo nguồn gốc, độc lập với chunk ID.**

| Trường | Quy tắc |
|---|---|
| `question_id` | ID ổn định trong một dataset version |
| `question_family_id` | ID nhóm câu đồng nghĩa/gần trùng để chia tập không rò rỉ |
| `question` | Câu hỏi tiếng Việt và phạm vi cần trả lời rõ ràng |
| `document_ids` | Phạm vi tài liệu được phép dùng; nếu không giới hạn thì ghi quy ước toàn bộ corpus snapshot |
| `answerable` | Boolean do người gán nhãn xác định trên corpus snapshot đã chốt |
| `question_type` | `single_evidence`, `multi_evidence` hoặc `unanswerable` |
| `reference_answer` | Đáp án mong đợi cho câu có đáp án; `null` nếu thiếu bằng chứng |
| `required_claims` | Các ý tối thiểu phải có; dùng chấm đúng/đủ, không yêu cầu khớp từng chữ |
| `evidence_sets` | Danh sách các tập bằng chứng thay thế nhau; ít nhất một tập phải đầy đủ với câu có đáp án |
| `unanswerable_reason` | Lý do thiếu bằng chứng; `null` với câu có đáp án |
| `annotator`, `reviewer`, `review_status` | Người tạo, người kiểm tra khác và trạng thái đã thống nhất |
| `dataset_version`, `corpus_snapshot_id` | Phiên bản nhãn và snapshot nội dung dùng khi gán nhãn |

Mỗi phần tử trong `evidence_sets` là một tập bằng chứng đủ để trả lời: OR giữa các tập, AND giữa các span trong một tập. Ví dụ câu hỏi cần cả thời hạn và điều kiện thì một tập phải chứa bằng chứng cho cả hai. Nếu cùng câu trả lời xuất hiện ở tài liệu khác, tạo một tập thay thế đầy đủ; không gộp tất cả nguồn thay thế thành các bằng chứng bắt buộc. Câu thiếu bằng chứng có `evidence_sets: []`, kèm lý do và phạm vi đã kiểm tra.

Mỗi span chứa `document_id`, `document_version`, `page_number`, `start_offset`, `end_offset`, `quote` và `canonical_text_sha256` của trang. Trang bắt đầu từ 1 trong PDF chuẩn. Offset bắt đầu từ 0, khoảng nửa mở `[start_offset, end_offset)`, đếm Unicode code points như phép cắt chuỗi Python; không đếm byte UTF-8 hoặc UTF-16 code units trong JavaScript. Backend cung cấp text và offset cho UI, UI không tự suy offset bằng `String.length`.

Ràng buộc kiểm tra: `0 <= start_offset < end_offset <= len(page_text)` và `quote == page_text[start_offset:end_offset]`. Text theo trang được chuẩn hóa một lần theo `normalization_version` rồi lưu cố định cùng hash; không bỏ khoảng trắng/dấu hoặc đổi Unicode normalization sau khi gán offset. Đoạn đi qua trang phải tách thành nhiều span theo trang. Chỉ gán đoạn đủ ngắn để thể hiện một bằng chứng cần thiết; không lấy cả trang nếu một câu đã đủ. Các bảng hoặc câu cần nhiều ô/đoạn dùng nhiều span trong cùng tập.

Một câu nhiều bằng chứng có dạng minh họa sau; các ID và nội dung chỉ là ví dụ cấu trúc:

```json
{
  "question_id": "q_multi_001",
  "question_family_id": "family_001",
  "question": "Điều kiện và thời hạn thực hiện thủ tục là gì?",
  "document_ids": ["doc_001", "doc_002"],
  "answerable": true,
  "question_type": "multi_evidence",
  "reference_answer": "Đáp án được người gán nhãn đối chiếu nguồn.",
  "required_claims": ["Điều kiện thực hiện", "Thời hạn thực hiện"],
  "evidence_sets": [
    {"set_id": "set_a", "spans": ["span_condition", "span_deadline"]},
    {"set_id": "set_b", "spans": ["span_equivalent_summary"]}
  ],
  "unanswerable_reason": null
}
```

Trong file gold thật, các giá trị `spans` trên được thay bằng đối tượng span đầy đủ, không dùng ID không có bản ghi nguồn. Một người soạn và một người khác kiểm tra mọi câu; bất đồng được đối chiếu PDF chuẩn. Câu chưa giải quyết bất đồng không đi vào bản benchmark đã khóa.

**Đánh giá theo từng tầng để xác định nguyên nhân sai.**

| Tầng | Đầu vào và phép đo | Cách phân biệt lỗi |
|---|---|---|
| Ingestion/provenance | PDF chuẩn, text theo trang, source spans | Bằng chứng có trong file nhưng trích xuất thiếu/sai hoặc không ánh xạ về trang |
| Retrieval | Câu hỏi và snapshot, chưa gọi LLM | Đo ứng viên dense/BM25/fusion có tìm được gold hay không |
| Reranking | Giữ nguyên tập ứng viên; so thứ hạng trước/sau | Gold có trong ứng viên nhưng bị đẩy ra khỏi top-k hoặc bị bỏ khi giới hạn context |
| Generation có retrieval thật | Câu hỏi và context thực sự đưa vào LLM | Context đủ nhưng câu trả lời sai/thiếu hoặc không được context hỗ trợ |
| Generation với gold context | Thay retrieval bằng bằng chứng chuẩn, giữ LLM/prompt/budget | Kiểm tra giới hạn đọc hiểu và sinh câu trả lời; đây là phép chẩn đoán, không phải kết quả RAG vận hành |
| Citation | Các khẳng định và liên kết nguồn được trả về | Nguồn hợp lệ về cấu trúc nhưng không hỗ trợ câu trả lời, hoặc nội dung đúng nhưng gắn sai nguồn |
| Abstention | Câu có/không có bằng chứng và trạng thái trả lời | Từ chối đúng, từ chối nhầm, hoặc trả lời khi thiếu bằng chứng |

Lưu danh sách ứng viên trước rerank, thứ hạng sau rerank và context sau cắt token. Phân biệt lỗi reranker với lỗi context packing: gold đứng trong top-k nhưng bị mất do giới hạn token thuộc bước chọn context. Ghi một nguyên nhân chính và các nguyên nhân phụ; báo cáo không quy toàn bộ lỗi cho LLM.

**Recall và MRR dùng quy tắc ánh xạ nguồn cố định giữa các phương pháp chunking.**

Đối với một câu có đáp án, ký hiệu `H_k` là top-k hit sau khử trùng theo chunk và trước cắt context. Ánh xạ mỗi hit thành các khoảng nguồn thực sự xuất hiện trong text hit; không tính toàn bộ trang chỉ vì metadata ghi trang đó. Một gold span được thu hồi khi hợp các khoảng của `H_k` trên đúng tài liệu, phiên bản và trang bao phủ toàn bộ span. Các hit trùng lặp không được tính nhiều lần.

`Evidence Recall@k(q)` là tỷ lệ span được thu hồi trong một tập bằng chứng hợp lệ; nếu có nhiều tập thay thế, lấy giá trị lớn nhất giữa các tập. `Recall@k` trong báo cáo dự án là trung bình theo câu của giá trị này, đồng thời ghi tên đầy đủ Evidence Recall để tránh nhầm với recall của chunk ID. Câu không có đáp án không có mẫu số bằng chứng nên không tham gia retrieval recall.

`All-evidence@k` là tỷ lệ câu có ít nhất một tập bằng chứng được thu hồi đầy đủ. Chỉ số này cần đi kèm Recall để nhận ra hệ thống tìm được một phần nhưng vẫn thiếu bằng chứng cho câu nhiều đoạn.

`MRR@10` dùng hạng 1-based của hit đầu tiên tự chứa trọn ít nhất một gold span thuộc bất kỳ tập hợp lệ nào; nếu không có thì điểm bằng 0. MRR đo bằng chứng hữu ích đầu tiên, không đo việc tìm đủ mọi bằng chứng. Span vắt qua ranh giới chunk có thể được hợp nhiều hit để tăng Evidence Recall nhưng không làm một hit riêng trở thành relevant cho MRR; báo cáo quy tắc này và giữ nguyên cho mọi cấu hình. Dùng gold span nhỏ, có ý nghĩa để giảm lệch do độ dài gán nhãn.

Gọi `/api/v1/search` với `retrieval_config.top_k = 10` để có đủ danh sách đo MRR@10; từ cùng danh sách lấy top 5 để tính Recall@5. Không tính MRR@10 từ response chỉ yêu cầu top 5. Số ứng viên ban đầu, RRF, giới hạn rerank và giới hạn context phải nằm trong cấu hình đã lưu. Với so sánh trước/sau rerank, dùng cùng tập ứng viên và cùng budget; không đổi đồng thời retriever hoặc tăng số ứng viên rồi gán toàn bộ cải thiện cho reranker.

Trên câu answerable, truy xuất trả lỗi được ghi riêng và tính recall/MRR bằng 0 trong chỉ số vận hành trên toàn bộ câu dự kiến. Có thể báo thêm chỉ số chỉ trên các request thành công nhưng phải ghi rõ mẫu số; không bỏ request lỗi khỏi báo cáo chung.

**Generation và citation được chấm theo rubric chung.**

| Chỉ số | Quy tắc |
|---|---|
| Độ đúng câu trả lời | `correct`: đủ ý bắt buộc, không sai hoặc thêm khẳng định không được hỗ trợ; `partial`: đúng một phần nhưng thiếu ý; `incorrect`: có lỗi nội dung hoặc kết luận không có bằng chứng |
| Citation validity | Liên kết trỏ tới nguồn thuộc context, đúng document version/trang, quote khớp text chuẩn và source còn hiệu lực; yêu cầu cấu trúc là 100% trên response phát hành |
| Citation precision | Số liên kết claim–citation mà nguồn thực sự hỗ trợ claim / tổng liên kết claim–citation được đưa ra |
| Citation coverage | Số khẳng định cần dẫn chứng được gắn ít nhất một nguồn hỗ trợ / tổng khẳng định cần dẫn chứng |
| Answer coverage | Số câu hệ thống trả lời / tổng request hợp lệ trong bộ đánh giá; báo cùng độ đúng để tránh hệ thống từ chối gần hết nhưng precision cao |
| Độ đúng có điều kiện | Chấm riêng các câu có context thực sự đủ bằng chứng để chẩn đoán generation; không thay chỉ số end-to-end |
| Hiệu năng | Thời gian từng tầng và toàn luồng, p50/p95, số request lỗi/timeout, token/chi phí, thời gian index và RAM/VRAM |

Một citation đúng ID nhưng không hỗ trợ claim là lỗi ngữ nghĩa. Câu trả lời không có citation hoặc không có khẳng định cần dẫn chứng có mẫu số citation precision bằng 0 thì metric đó là `null`, không tự đặt 1. Một câu được trả lời mà thiếu nguồn bắt buộc vẫn bị đánh dấu vi phạm contract/nghiệm thu. Kết quả `insufficient_evidence` không được chấm như câu trả lời đúng chỉ vì không chứa khẳng định sai; nó được đánh giá ở nhóm abstention.

Chấm generation với gold context chỉ thực hiện trên câu có đáp án và phải ghi rõ là oracle-context. Giới hạn context phải đủ chứa một tập gold đầy đủ; nếu không đủ, ghi ca đó là không khả dụng cho phép thử này, công bố số lượng, không cắt bằng chứng rồi kết luận LLM đọc sai. LLM-as-judge nếu có chỉ hỗ trợ sàng lọc; kết quả chính dùng rubric được người kiểm tra đối chiếu nguồn.

**Abstention coi “không đủ bằng chứng” là lớp dương và phân biệt lỗi hệ thống.**

| Gold | Response `insufficient_evidence` | Response `answered` | Lỗi/timeout/non-2xx |
|---|---|---|---|
| Không đủ bằng chứng | TP: từ chối đúng | FN: trả lời khi không đủ bằng chứng | `E_unanswerable`: lỗi, không coi là từ chối |
| Có đủ bằng chứng | FP: từ chối nhầm | TN: quyết định trả lời; nội dung vẫn phải chấm riêng | `E_answerable`: lỗi, không coi là từ chối |

- `Abstention precision = TP / (TP + FP)`.
- `Abstention recall` trên các quyết định hợp lệ = `TP / (TP + FN)`; luôn ghi số quyết định hợp lệ và số lỗi bên cạnh.
- `Abstention recall_all`, chỉ số vận hành trên tất cả câu thiếu bằng chứng = `TP / (TP + FN + E_unanswerable)`; báo bắt buộc để lỗi không làm tăng thành tích bằng cách bị loại khỏi mẫu số.
- Tỷ lệ từ chối nhầm trên tất cả câu có đáp án = `FP / (FP + TN + E_answerable)`; đồng thời báo tỷ lệ lỗi của nhóm này và tỷ lệ chỉ trên các quyết định hợp lệ khi cần.
- Mẫu số bằng 0 trả metric `null` và hiển thị “không có mẫu”, không trả 0 hoặc 1 tùy ý.

HTTP error, lỗi provider và trạng thái nghiệp vụ thiếu bằng chứng không được đổi qua lại. Bộ chạy lưu outcome và error code cho mọi `question_id`, không chỉ lưu câu thành công. Sai nội dung trên câu answerable thuộc generation; quyết định trả lời của nó vẫn là TN trong bảng abstention, vì hai phép đo kiểm tra hai việc khác nhau.

**Confidence mặc định là `null`; calibration là thí nghiệm có điều kiện.**

Không dùng cosine, BM25, RRF, raw reranker score hoặc sigmoid của những điểm đó làm xác suất câu trả lời đúng. Không lấy lời tự đánh giá của LLM làm confidence đã hiệu chỉnh. Với MVP chưa có bộ ước lượng được đánh giá, response trả `confidence: null`; với response thiếu bằng chứng luôn trả `confidence: null` theo API contract.

Nếu nhóm triển khai bộ ước lượng, trước tiên định nghĩa rõ sự kiện cần dự đoán: “câu trả lời được phát hành đạt mức correct theo rubric và mọi khẳng định cần thiết được bằng chứng hỗ trợ”. Nhãn nhị phân của calibrator xuất phát từ việc chấm câu trả lời của pipeline cố định, không chỉ từ `answerable` của câu hỏi. Câu hỏi có đáp án vẫn có thể bị LLM trả lời sai.

Chỉ huấn luyện/hiệu chỉnh trên phần dữ liệu tách riêng khỏi test cuối: chia dev thành tập fit và calibration-validation theo nhóm, hoặc dùng grouped out-of-fold predictions trong dev. Không vừa fit vừa công bố độ hiệu chỉnh trên cùng các prediction. Chốt pipeline, estimator và ngưỡng trước khi mở test; đổi model/prompt/context policy làm thay đổi phân phối thì phải đánh giá lại estimator.

Với chỉ 90 câu dev, dữ liệu có thể không đủ để kết luận calibration đáng tin cậy. Không có số mẫu tối thiểu chung bảo đảm hiệu chỉnh tốt: nhóm phải công bố kích thước tập, số lỗi thực sự, phân bố score và độ bất định. Nếu validation không đủ hai loại kết quả đúng/sai hoặc quá ít mẫu để đánh giá, giữ confidence null và ghi thí nghiệm chưa đủ điều kiện. Không tạo mức “high” vì thiếu số liệu.

Nếu đủ điều kiện, báo Brier score, reliability diagram và ECE với số bin/quy tắc bin được định trước; công bố số mẫu mỗi bin và khoảng bất định khi khả thi. So sánh trước/sau calibration trên dữ liệu validation độc lập. Các mốc `low`/`medium`/`high` được chọn từ validation và version cùng estimator; API chỉ công bố score trong [0,1] khi kiểm tra đạt tiêu chí đã chốt. Estimator version, label definition và calibration dataset version phải nằm trong run manifest. Kết quả test cuối dùng để đánh giá, không quay lại điều chỉnh rồi gọi là test độc lập.

**Mỗi lần benchmark phải có manifest đủ để tái lập và không truy xuất lẫn phiên bản.**

Manifest lưu tối thiểu:

- `run_id`, thời điểm UTC, người chạy, code commit/hash và dependency lock hash.
- Dataset version/hash, danh sách question IDs và split; corpus manifest/hash và `corpus_snapshot_id`.
- `index_version` được request pin và `resolved_index_version` thực tế; danh sách `document_version`, `embedding_model_version`, `chunking_config_id`, normalization/tokenizer versions.
- Cấu hình BM25, RRF, candidate budgets, reranker ID/revision, top-k và context token budget.
- LLM ID/revision hoặc định danh provider trả được, prompt hash/version, generation parameters và seed nếu provider hỗ trợ.
- Estimator/calibration version nếu có; nếu không có ghi `null`.
- Phần cứng, RAM/VRAM, runtime, warm-up/caching policy, mức đồng thời, timeout/retry policy và giới hạn chi phí.
- Deletion/visibility epoch nội bộ ở đầu/cuối run cùng các sự kiện liên quan; raw predictions, error codes, stage timings và phép chấm.

Mỗi request benchmark chọn `index_version` cụ thể. Nếu response không khớp phiên bản đã chọn hoặc corpus snapshot mong đợi thì run không hợp lệ. Không tự fallback sang active index mới hoặc sang tập tài liệu còn sống mà không ghi thay đổi. Query embedding phải dùng đúng model của index được chọn.

Theo quy tắc vòng đời index của dự án, xóa một tài liệu sẽ thu hồi các index generation chứa tài liệu đó; pinned request nhận `409 INDEX_VERSION_UNAVAILABLE`. Active retrieval có thể trả `503 INDEX_NOT_READY` cho tới khi có successor sạch. Nếu một phiên bản dùng trong benchmark bị thu hồi trong lúc chạy, dừng và đánh dấu toàn run không hợp lệ, lưu log phục vụ chẩn đoán rồi chạy lại trên snapshot sạch. Không gộp các kết quả trước/sau xóa làm một bảng so sánh duy nhất. Corpus hoặc gold thay đổi cũng cần version/run mới; kết quả lịch sử vẫn giữ nhãn nguồn gốc nhưng không được trình bày như đo trên corpus hiện tại.

Tái lập có nghĩa là cùng dữ liệu và cấu hình được ghi rõ; API LLM có thể không hoàn toàn xác định. Công bố những yếu tố không khóa được, và nếu chạy lặp thì chốt trước số lần lặp, báo phân bố/độ biến thiên; không chỉ chọn lần chạy tốt nhất.

**Thứ tự thí nghiệm giữ một biến chính thay đổi ở mỗi bước.**

| Thử nghiệm | Biến thay đổi | Giữ cố định và đầu ra |
|---|---|---|
| E1: chunking | Fixed-size, recursive, heading-aware | Cùng embedding và retrieval; cùng quy tắc gold, corpus và giới hạn token; A phụ trách |
| E2: embedding | Hai model đã chạy thử phần cứng | Cùng chunking và phạm vi tài liệu; đúng query prefix/tokenizer từng model; B phụ trách |
| E3: retrieval | BM25, dense, hybrid | Cùng chunking/embedding/corpus; ghi riêng candidate budgets; B phụ trách |
| E4: reranking | Tắt/bật reranker | Giữ nguyên candidates trước rerank; đo trước/sau và context cuối; B phụ trách |
| E5: generation/abstention | Cấu hình cuối và baseline định trước | Cùng LLM, prompt và budget; end-to-end, conditional và oracle-context ghi thành bảng riêng; C phụ trách |
| E6: confidence, nếu đủ dữ liệu | Có/không calibration | Tập fit/validation độc lập, semantics/estimator khóa; không bắt buộc có score để đạt MVP |

Đây là thiết kế tuần tự phù hợp nhóm ba người, không khẳng định đã khảo sát đầy đủ mọi tương tác. Ablation tuần 7 tắt từng thành phần của cấu hình cuối đã chốt để xác định đóng góp; không thay nhiều tham số đồng thời. Nếu nguồn lực không đủ chạy tất cả biến thể trên test, định trước subset trước khi mở nhãn test và báo rõ.

**Lịch và nghiệm thu bám mốc MVP tuần 4.**

| Thời gian | Việc cần hoàn thành |
|---|---|
| Tuần 1 | Chốt gold schema, rubric, metric, snapshot semantics; 15 câu dev mẫu được kiểm tra chéo |
| Tuần 2–3 | Mỗi người soạn 60 câu; kiểm tra chéo; xây runner retrieval/generation độc lập và fixture lỗi |
| Tuần 4 | MVP toàn luồng; khóa dataset version đầu, group split và baseline đo được |
| Tuần 5–6 | Thí nghiệm dev, phân tích lỗi theo tầng, chọn cấu hình; calibration chỉ khi đủ điều kiện |
| Tuần 7 | Ablation, đóng cấu hình và chạy test; không tối ưu lại bằng nhãn test |
| Tuần 8 | Chốt báo cáo, giới hạn, manifest và kịch bản demo; ghi rõ lỗi còn tồn tại |

| Hạng mục nghiệm thu | Bằng chứng bàn giao |
|---|---|
| Upload PDF/DOCX | Corpus fixture hợp lệ xử lý thành công; file lỗi/scan báo đúng trạng thái |
| Provenance | 100% chunk có document version và vị trí trang/span hợp lệ trên corpus nghiệm thu; kiểm tra quote/offset tự động |
| Retrieval | Bảng Recall@5 và MRR@10 cùng quy tắc relevance, số mẫu, lỗi và cấu hình |
| Reranking | Bảng trước/sau trên cùng tập ứng viên và phân tích ca cải thiện/suy giảm |
| Citation | 100% citation ánh xạ nguồn hợp lệ về cấu trúc trên response phát hành; semantic precision/coverage được đo riêng |
| Abstention | Precision/recall, recall_all, confusion counts và lỗi hệ thống riêng |
| Confidence | Null khi chưa đủ điều kiện; nếu có score phải kèm báo cáo calibration và version |
| Reproducibility | Manifest, config, dataset/corpus version và kết quả đầy đủ; có thể chạy lại lệnh benchmark được README mô tả |
| Deployment | Khởi chạy ứng dụng bằng Docker Compose và thực hiện kịch bản demo |
| Prompt injection | Bộ ca tài liệu chứa chỉ thị đổi vai trò/nguồn/trang; hệ thống giữ tài liệu ở vai trò dữ liệu và không thực thi chỉ thị |

Các điều kiện 100% về provenance/citation là bất biến cấu trúc cần kiểm tra, không phải lời hứa 100% câu trả lời đúng. Các mức chất lượng retrieval, generation, abstention và latency được công bố sau benchmark; nếu nhóm đặt ngưỡng mục tiêu thì khóa trên dev trước test và báo kết quả thực tế, kể cả khi chưa đạt. Chưa có phép đo nào trong tài liệu này là kết quả thực nghiệm.
