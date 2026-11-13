**Các quy tắc kỹ thuật dưới đây là hợp đồng triển khai của Vietnamese RAG trước khi viết mã ứng dụng.**

Phạm vi MVP: một nhóm người dùng, một worker ghi index, metadata SQLite, file storage, Qdrant và BM25. API công khai tuân theo [API contract](api-contract.md); bộ đánh giá tuân theo [evaluation protocol](evaluation-protocol.md). Các quy tắc trong tài liệu này là quyết định thiết kế của dự án, chưa phải hành vi đã được triển khai hoặc kết quả kiểm thử.

Mỗi thay đổi schema hoặc quy tắc liên quan từ hai module trở lên phải cập nhật hợp đồng cùng PR. A sở hữu ingestion/storage/lifecycle, B sở hữu index/retrieval, C sở hữu generation/citation/UI. Người sử dụng dữ liệu phải review thay đổi của người tạo dữ liệu; không đổi tên trường hoặc ý nghĩa `null` chỉ ở một phía.

**Phiên bản dữ liệu và index phải đủ để xác định chính xác một lần chạy.**

| Trường | Ý nghĩa và quy tắc |
|---|---|
| `document_id` | ID do backend tạo, ổn định trong vòng đời tài liệu; không lấy filename làm ID |
| `document_version` | Phiên bản nội dung nguồn và biểu diễn text chuẩn theo trang; không đổi nội dung phía sau một version đã công bố |
| `embedding_model_version` | Model ID + revision/weights hash + tokenizer revision + cấu hình encode, prefix và normalization; không chỉ dùng tên model |
| `chunking_config_id` | ID bất biến của thuật toán, phiên bản implementation, tokenizer, kích thước, overlap và quy tắc qua trang/heading |
| `index_version` | ID một generation, gắn với manifest chứa corpus snapshot, các document version, embedding version, chunking config và BM25 preprocessing/config |
| `corpus_manifest_hash` | Hash của manifest chuẩn hóa, sắp xếp ổn định; không phụ thuộc thứ tự đọc file |
| `retrieval_config_id` | Hash cấu hình retrieval đã resolve: nhánh bật/tắt, candidate count, fusion, reranker version, top-k và context budget |

Manifest index còn ghi vector dimension, distance metric, tokenizer và chuẩn hóa BM25, chunk-ID manifest/hash, số chunk kỳ vọng, phiên bản schema và thời điểm tạo. File cấu hình có nội dung bất biến; thay đổi một trường phải tạo ID/version mới. Thông tin máy, dependency lockfile và code revision được ghi vào benchmark run, không dùng nhãn model chung chung để suy ra cấu hình.

Một `index_version` chứa đồng thời tham chiếu đến dense index và BM25 snapshot của cùng tập chunk. Dù một request chỉ dùng BM25, generation xuất bản của MVP vẫn phải có cả hai index nhất quán. Những thử nghiệm với embedding hoặc chunking khác nhau tạo generation riêng; không ghi đè generation đã xuất bản.

**Một generation được dựng trong staging, kiểm chứng rồi mới chuyển sang phục vụ.**

1. Worker đọc manifest tài liệu/version cần index và lưu job bền vững; lấy lease để chỉ có một writer thực hiện publish/lifecycle tại một thời điểm.
2. Tạo `index_version` mới và namespace/collection/snapshot staging riêng. Dựng chunk, dense index và BM25 cùng manifest. Thêm tài liệu cũng tạo snapshot kế tiếp; với corpus MVP nhỏ, ưu tiên rebuild rõ ràng thay vì cập nhật hai index độc lập.
3. Kiểm tra số chunk, tập chunk ID/hash, document version, provenance, vector dimension và khả năng đọc cả hai index. Không chỉ kiểm tra số lượng vì hai tập khác nhau vẫn có thể cùng kích thước.
4. Recheck tombstone/deletion và phiên bản corpus trước publish. Nếu tài liệu bị thu hồi trong lúc build, staging đó không được công bố; tạo lại snapshot không chứa tài liệu bị thu hồi hoặc đánh dấu job thất bại có thể retry theo chính sách nội bộ.
5. Chỉ khi artifact đã tồn tại bền vững và đọc được, dùng một transaction SQLite để ghi generation sẵn sàng và cập nhật `active_index_version`. Chuyển pointer không thể biến thao tác ở Qdrant/BM25 thành transaction phân tán; tính nhất quán đến từ staging và không cho request đọc artifact chưa được công bố.
6. Sau publish, request mới thấy generation mới; request đã pin generation cũ tiếp tục dùng generation cũ nếu nó chưa bị thu hồi. Artifact staging bị bỏ dở được phát hiện qua job ledger để retry hoặc dọn dẹp sau crash.

Mỗi request search/chat resolve generation đúng một lần lúc bắt đầu. Nếu client không chọn `index_version`, pin `active_index_version` tại thời điểm đó; nếu client chọn rõ, dùng đúng version ấy. Query embedding phải dùng model/revision/prefix/normalization thuộc manifest đã pin, không dùng model mới nhất trong biến môi trường. BM25 dùng đúng preprocessing và corpus snapshot tương ứng.

Nếu version được chọn không sẵn sàng, bị thu hồi hoặc artifact không còn dùng được, trả lỗi theo API contract; không tự đổi sang generation khác. Mỗi response thành công phải có trace chứa version đã resolve và cấu hình retrieval thực tế để kiểm tra lại. Không trộn dense kết quả từ generation này với BM25 của generation khác.

**Trạng thái tài liệu phản ánh lifecycle; khả năng truy vấn còn phụ thuộc generation.**

| Trạng thái | Ý nghĩa | Chuyển trạng thái hợp lệ |
|---|---|---|
| `queued` | Đã lưu file/job, chờ ingestion | `processing`, `deleting` |
| `processing` | Đang parse/chunk/build hoặc chờ publish | `ready`, `failed`, `deleting` |
| `ready` | Ingestion đã thành công vào ít nhất một generation lịch sử | `deleting` |
| `failed` | Ingestion chưa hoàn tất; lỗi có code và thông tin retry | `queued` qua retry hợp lệ, hoặc `deleting` |
| `deleting` | Đã thu hồi quyền sử dụng nội dung, đang cleanup | `delete_failed`, hoặc hoàn tất và chỉ còn tombstone |
| `delete_failed` | Cleanup chưa xong; nội dung vẫn bị thu hồi | `deleting` khi retry xóa |

`ready` không bảo đảm tài liệu tồn tại trong mọi generation hoặc đang truy vấn được. `available_index_versions` chỉ chứa generation sẵn sàng, chưa thu hồi và có đúng document version; có thể rỗng sau khi một generation bị thu hồi. Search/chat kiểm tra membership trong generation đã pin, không chỉ kiểm tra `Document.status`.

Không có document nội dung ở trạng thái `deleted`: sau cleanup chỉ giữ tombstone tối thiểu ngoài bảng metadata nội dung. Tra cứu một ID đã xóa trả `410 Gone`; ID chưa từng tồn tại trả `404 Not Found`. Trước khi cleanup hoàn tất, endpoint chi tiết/trạng thái vẫn cho theo dõi `deleting` hoặc `delete_failed`, nhưng source/search/chat không được đọc nội dung của tài liệu đó.

**Retry ingestion phải idempotent và không được làm sống lại tài liệu đã xóa.**

- `POST /api/v1/documents/{id}/retry` chỉ dành cho ingestion có trạng thái `failed`. Không dùng endpoint này để đổi model, đổi chunking, rebuild một tài liệu `ready` hoặc retry xóa.
- Transaction chuyển `failed → queued`, tạo attempt và job mới gắn với version/config được retry. Nếu hai request retry cùng đến, chỉ một request được tạo attempt; request còn lại nhận conflict hoặc kết quả replay theo quy tắc idempotency trong API contract.
- Các thao tác side effect được thiết kế để chạy lại an toàn: ID chunk/point xác định được từ version/config/provenance, staging có namespace riêng, upsert cùng ID không sinh bản lặp. Không tuyên bố bảo đảm exactly-once cho toàn bộ chuỗi ghi nhiều store.
- Worker kiểm tra lifecycle trước đọc file, trước ghi/publish và sau khi phục hồi job. Lease hết hạn không có nghĩa được bỏ qua tombstone.
- Tài liệu bị thu hồi không được retry ingestion; một lần upload mới cùng nội dung sau đó phải có lifecycle mới và ID mới theo chính sách upload của API, không tái sử dụng ID đã bị tombstone.

**Xóa là thu hồi ngay, cleanup sau; mọi generation chứa tài liệu đều phải được xử lý.**

1. Khi chấp nhận DELETE, transaction SQLite ghi tombstone/revocation, chuyển tài liệu sang `deleting`, tạo deletion job và đánh dấu thu hồi tất cả generation có tài liệu đó. Hủy quyền publish của ingestion/build đang chứa tài liệu. Không đợi Qdrant hoặc BM25 xóa xong mới ngăn truy cập.
2. Request mới kiểm tra revocation trước khi đọc nguồn hoặc thực hiện retrieval. Generation bị thu hồi không còn được phục vụ, kể cả client chỉ chọn một tài liệu khác trong generation đó. Đây là quy tắc cố ý nghiêm ngặt của MVP để giữ ý nghĩa snapshot.
3. Request đã chạy phải recheck generation và nguồn trước khi đưa context vào LLM, trước khi trả answer/search và trước khi mở source. Nếu generation đã pin bị thu hồi trong quá trình xử lý, bỏ kết quả và trả `409 SOURCE_SET_CHANGED`; không xóa citation rồi giữ nguyên câu trả lời vốn có thể chứa thông tin đã thu hồi. Các byte/response đã gửi trước khi DELETE được chấp nhận không thể thu hồi ngược lại.
4. Deletion worker dọn Qdrant points/collections liên quan, BM25 snapshots, chunk/text/embedding cache, file gốc và PDF chuẩn, bản lưu response/context có chứa nội dung nếu hệ thống có lưu. Dò theo document ID/version trên toàn bộ generations, gồm staging, benchmark và generation không còn active; không chỉ dọn active index.
5. Nếu active generation bị thu hồi, worker dựng snapshot kế tiếp từ các tài liệu còn hợp lệ rồi publish theo quy trình staging. Trong khoảng chưa có active generation sạch, request dùng mặc định trả `503 INDEX_NOT_READY`; request chỉ rõ generation đã thu hồi trả `409 INDEX_VERSION_UNAVAILABLE`. Không tự phục vụ một corpus khác dưới cùng index version.
6. Giữ deletion ledger và dữ liệu định vị cần cleanup cho đến khi từng store xác nhận hoàn tất. File/text có thể được xóa trong bước cleanup; chỉ purge metadata nội dung khi các store đã được kiểm chứng. Khi lỗi giữa chừng, giữ trạng thái `delete_failed`, retry từ phần còn thiếu bằng thao tác idempotent.
7. Chỉ trả kết quả DELETE hoàn tất `204 No Content` khi cleanup nội dung ở mọi store và metadata đã xong; nếu còn đang làm, phản hồi bất đồng bộ theo API contract. Giữ tombstone tối thiểu gồm ID, thời điểm thu hồi/xóa và trạng thái hoàn tất; không giữ filename, quote, text, embedding hoặc đường dẫn nội dung đã xóa.

Gọi lại DELETE là cách retry một deletion thất bại; DELETE lặp trong khi đang xử lý không tạo cleanup cạnh tranh. DELETE vào ID đã hoàn tất trả `204` theo quy tắc idempotent của API; các GET vào ID ấy trả `410`. Không xóa ledger trước khi hoàn tất, vì khi đó worker không còn biết store nào cần dọn tiếp.

Manifest của generation cũ vẫn là bản mô tả bất biến về dữ liệu từng được dựng, nhưng generation bị thu hồi được đánh dấu không khả dụng và không còn được tuyên bố tái lập nguyên trạng. Chỉ giữ manifest/audit không chứa dữ liệu nội dung theo phạm vi đã cho phép; nếu manifest chứa nội dung cần xóa, phải dọn phần đó và giữ lý do không còn tái lập. Benchmark sau deletion dùng snapshot/version mới và ghi rõ thay đổi corpus.

**Provenance phải hình thành ngay khi trích xuất, trước chunking và embedding.**

- Lưu file gốc, hash, PDF chuẩn để xem nguồn và text chuẩn theo trang. DOCX dùng trang của PDF chuyển đổi đã được lưu cố định; không tính trang bằng số đoạn văn.
- Trang bắt đầu từ 1, tính theo thứ tự vật lý trong PDF chuẩn. Số in trên trang nếu lưu là trường phụ, không thay thế `page_number`.
- Text chuẩn theo trang dùng Unicode NFC và xuống dòng LF. Sau khi chốt text/version, không làm sạch lại tại chỗ. Offset là chỉ số Unicode code point, bắt đầu từ 0 và kết thúc không bao gồm ký tự tại `end_offset`; frontend JavaScript không được mặc định coi offset là UTF-16 index.
- Mỗi source span phải có `document_id`, `document_version`, `page_number`, `start_offset`, `end_offset`; kiểm tra range nằm trong text trang. Chunk chứa nhiều trang phải giữ nhiều span; citation một trang lấy một quote liên tục trên trang đó, cần dẫn nhiều trang thì tạo nhiều citation.
- Chuẩn hóa/tách từ phục vụ BM25 tạo biểu diễn tìm kiếm riêng; embedding dùng input theo model contract. Không dùng text đã bỏ dấu hoặc đổi cấu trúc làm quote nếu không giữ được ánh xạ về text chuẩn.
- Chunk ID gắn với document version, chunking config, các span và content hash; không thay text của chunk dưới cùng ID. Dense/BM25 phải dùng chung chunk ID và không đánh đồng chunk ID với source ID do API cấp trong một request.

**Generation chỉ được sử dụng bằng chứng được backend cấp và phải tách lỗi khỏi thiếu bằng chứng.**

Backend gán source ID cho context đã lọc, pin document/index version và giữ ánh xạ sang metadata. LLM chỉ được chọn những ID đó; filename, page number và quote hợp lệ do backend resolve/kiểm tra. Không nhận đường dẫn file, URL nguồn hoặc trang do LLM tự tạo làm dữ liệu đáng tin cậy.

Điều kiện tối thiểu trước khi trả `answered` gồm schema hợp lệ, citation ID thuộc context, nguồn chưa bị thu hồi, trang/span/quote hợp lệ và câu trả lời vượt qua quy tắc kiểm tra bằng chứng đã chốt. Việc citation trỏ đến một nguồn tồn tại không tự chứng minh claim được nguồn hỗ trợ; metric citation precision/coverage và chấm nội dung trong bộ đánh giá xử lý phần này.

Nếu tài liệu cùng chủ đề nhưng không chứa thông tin được hỏi, vẫn trả `insufficient_evidence`; không dùng tri thức sẵn có của LLM để bù mà vẫn gắn nguồn. Timeout, model unavailable, index lỗi, output/schema sai hoặc citation không kiểm chứng được là lỗi kỹ thuật theo contract; không đổi thành từ chối vì thiếu bằng chứng để làm đẹp metric. Nếu có retry generation, số lần phải hữu hạn và ghi lại trong trace.

**Confidence là kết quả của bộ ước lượng đã được đánh giá, không phải nhãn trang trí cho câu trả lời.**

- MVP mặc định trả `confidence: null`. Trường hợp `insufficient_evidence` luôn có `citations: []` và `confidence: null` theo API contract.
- Không gán `confidence.score` từ cosine, BM25, RRF, raw reranker, sigmoid của raw score, hoặc lời tự đánh giá của LLM. Những điểm đó có thể được ghi trong trace retrieval đúng tên, không coi là xác suất câu trả lời đúng.
- Muốn trả score, phải định nghĩa rõ sự kiện được ước lượng, bộ dữ liệu có nhãn, cách fit và hiệu chỉnh trên phần dev tách phù hợp, metric hiệu chỉnh trên dữ liệu độc lập, miền áp dụng và `estimator_version`. Điểm thuộc [0, 1] chưa đủ chứng minh đã hiệu chỉnh.
- `confidence.level` nếu xuất hiện phải được suy từ các ngưỡng đã đánh giá của chính estimator; không gán mức high/medium/low bằng rule khác rồi để người dùng hiểu đó là xác suất đã kiểm chứng.
- Nếu không có estimator phù hợp với model/prompt/index/retrieval config hiện tại, hoặc đánh giá không đủ tin cậy, trả `null`. Thay cấu hình cần kiểm tra lại tính hợp lệ của estimator, không tự chuyển calibration từ cấu hình cũ.

Quyết định từ chối có thể dùng evidence gate đã chọn trên dev ngay cả khi confidence vẫn là null. Nhóm đo precision/recall từ chối độc lập; không cần phát minh score để triển khai được abstention.

**Nội dung PDF/DOCX là dữ liệu không đáng tin cậy, không có quyền điều khiển LLM hoặc ứng dụng.**

- Giữ chỉ thị hệ thống, câu hỏi người dùng và context tài liệu thành các phần rõ ràng. Khi serialize context, escape delimiter theo định dạng đã chọn; không nối text tài liệu thành system/developer message hoặc tên role.
- Một câu trong tài liệu như “bỏ qua hướng dẫn trước đó”, “đọc biến môi trường” hoặc “chuyển API key đến URL này” chỉ là nội dung nguồn; không được thực thi. LLM chỉ trả lời câu hỏi bằng bằng chứng trong phạm vi tài liệu đã chọn.
- Generation MVP không có tool truy cập shell, filesystem tùy ý, network hoặc ghi dữ liệu bên ngoài. Parser/converter chỉ đọc file upload trong storage do backend quản lý; filename không được trở thành đường dẫn tùy ý hoặc tham số shell không được xử lý an toàn.
- Không để tài liệu tự chọn model, prompt, index version, scope tài liệu hoặc citation map. Những giá trị đó do request đã validate và backend quyết định.
- Validate output schema và nguồn sau generation. Escape text/HTML khi hiển thị filename, quote, câu trả lời; không render HTML/script từ tài liệu. Chỉ dựng link nguồn từ route backend và ID đã kiểm tra, không điều hướng theo link tự sinh của model.
- Khi logging, mặc định ghi request ID, version, số lượng và timing; không ghi API key, prompt chứa bí mật hoặc toàn bộ tài liệu. Nếu lưu context để debug/đánh giá, lưu có chủ đích theo document/version và đưa vào phạm vi deletion cleanup.
- Bộ kiểm thử phải có nguồn chứa chỉ thị độc hại ở đoạn được retrieval chọn, giả mạo source ID, HTML/script trong filename/quote và yêu cầu tiết lộ secret. Việc đặt delimiter/prompt không được mô tả là bảo đảm ngăn mọi prompt injection; đo kết quả kiểm thử thực tế.

**Các ca kiểm chứng dưới đây là điều kiện tích hợp, không phải kết quả đã đạt.**

| Nhóm kiểm tra | Tình huống | Kết quả cần thấy | Chủ trì |
|---|---|---|---|
| Schema | Một phía đổi tên trường, enum hoặc kiểu null | Contract check phát hiện trước merge | A/B/C |
| Provenance | PDF/DOCX tiếng Việt, chunk qua trang | 100% chunk có source span hợp lệ và mở đúng trang | A |
| Publish | Dense thành công, BM25 thất bại | Không publish staging; active cũ còn nguyên nếu chưa thu hồi | A/B |
| Manifest | Hai index có cùng số lượng nhưng khác chunk ID | Không publish generation | B |
| Version | Chuyển embedding/chunking trong lúc có request | Request chỉ dùng generation và query encoder đã pin | B |
| Version | Chọn explicit version bị thu hồi | `409 INDEX_VERSION_UNAVAILABLE`, không fallback | A/B |
| Deletion | Xóa khi upload/build đang chạy | Worker không publish lại tài liệu đã thu hồi | A/B |
| Deletion | Xóa khi chat đang chờ LLM | Recheck và trả `409 SOURCE_SET_CHANGED`; không trả answer cũ | A/C |
| Deletion | Qdrant hoặc file deletion lỗi giữa chừng | `delete_failed`, nội dung vẫn bị chặn; retry hoàn tất không sinh bản lặp | A/B |
| Deletion | Có nhiều generation và cache chứa tài liệu | Mọi bản nội dung được cleanup, metadata nội dung bị purge, còn tombstone tối thiểu | A/B |
| Deletion | Active generation bị thu hồi | Default trả `503 INDEX_NOT_READY` cho đến khi successor sạch được publish | A/B |
| Retry | Hai ingestion retry đồng thời; retry ID đã xóa | Không tạo hai attempt; không phục hồi ID đã tombstone | A |
| Citation | Model trả source ID/trang/quote không có trong context | Không trả `answered` với citation đó | C |
| Abstention | Có chủ đề liên quan nhưng thiếu đáp án | `insufficient_evidence`, citations rỗng, confidence null | B/C |
| Error | LLM timeout hoặc index không truy cập được | Lỗi kỹ thuật đúng contract, không tính thành abstention | A/B/C |
| Confidence | Estimator chưa được đánh giá hoặc sai config | Confidence null; raw scores chỉ thuộc trace retrieval | B/C |
| Injection | Nguồn chứa lệnh đổi hướng dẫn hoặc lấy secret | Không làm theo lệnh, không gọi tool bên ngoài, không lộ secret | C |
| UI | Quote/filename có HTML hoặc source URL giả | Hiển thị như text, chỉ dùng source route hợp lệ | C |
| Deployment | Khởi động từ môi trường sạch | Docker Compose dựng đủ dependency, health đúng trạng thái thực | A |

Trước khi bắt đầu code nghiệp vụ, A/B/C cần cùng xác nhận schema API và mẫu request/response, định nghĩa version/manifest, trạng thái retry/xóa và quy ước source span. Các mục này trở thành acceptance criteria của issue và contract/integration checks khi triển khai; không cần dựng sẵn toàn bộ hạ tầng production để chốt hợp đồng MVP.
