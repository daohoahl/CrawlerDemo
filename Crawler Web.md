# Crawler Web — Bản Báo Cáo Chi Tiết (Rút Gọn Production-Ready)

## 1) Bài toán và mục tiêu

Hệ thống thu thập dữ liệu bài viết từ RSS/Sitemap, chuẩn hóa URL, chống trùng, lưu vào PostgreSQL và cung cấp giao diện tra cứu + tải file export trên S3.

- **Quy mô mục tiêu: `~5,000 bài/ngày`, lưu vận hành `~100k bài`**  
  Cơ chế: dữ liệu được tách thành các batch crawl theo chu kỳ, không ghi trực tiếp từ worker vào DB.  
  Áp dụng trong bài: dùng SQS làm lớp đệm để hấp thụ spike, còn Lambda ghi DB theo nhịp ổn định hơn.

- **Scalability**  
  Cơ chế: tách producer (`crawler-worker`) và consumer (`Lambda ingester`) qua queue bất đồng bộ.  
  Áp dụng: worker scale theo CPU ASG, Lambda scale theo độ sâu queue nhưng bị governor bởi `maximum_concurrency`.

- **Robustness**  
  Cơ chế: at-least-once delivery của SQS + retry có kiểm soát + DLQ + rollback transaction.  
  Áp dụng: khi lỗi parse/DB/network, message không mất mà quay lại queue hoặc vào DLQ để điều tra.

- **Idempotency**  
  Cơ chế: khóa duy nhất `canonical_url` + `ON CONFLICT DO NOTHING` tại DB.  
  Áp dụng: dù message bị xử lý lại do timeout/retry thì dữ liệu vẫn không bị nhân bản.

- **Cost-aware (Scope 1)**  
  Cơ chế: chọn các dịch vụ managed nhưng bản nhỏ (t3.micro, single NAT, single-AZ DB) và giới hạn concurrency.  
  Áp dụng: vẫn giữ chuẩn vận hành production cơ bản nhưng tối ưu chi phí cho đồ án/lab.

---

## 2) Kiến trúc triển khai (Scope 1)

### Thành phần chính

- **`crawler-worker` (EC2 ASG)**  
  Cơ chế: chạy tiến trình crawl dài hạn, đọc nguồn RSS/Sitemap, gom batch rồi đẩy vào SQS.  
  Áp dụng: worker không giữ state nghiệp vụ; nếu instance chết thì ASG thay instance mới và tiếp tục vòng crawl.

- **`crawler-web` (FastAPI trên cùng EC2)**  
  Cơ chế: cung cấp API dashboard và trigger crawl thủ công, dùng DB query read-only cho UI.  
  Áp dụng: khi để `schedule_mode=idle`, web trở thành điểm điều phối crawl theo yêu cầu vận hành.

- **`SQS Standard + DLQ`**  
  Cơ chế: queue chính lưu message xử lý, DLQ giữ message fail nhiều lần để tách khỏi luồng chính.  
  Áp dụng: pipeline không nghẽn dây chuyền khi có poison message.

- **`Lambda ingester`**  
  Cơ chế: được trigger bởi SQS ESM, xử lý batch, commit DB, báo partial failures chính xác theo từng record.  
  Áp dụng: tăng/giảm throughput ingest linh hoạt mà không cần quản lý server consumer.

- **`RDS PostgreSQL`**  
  Cơ chế: lưu schema có ràng buộc rõ ràng, unique index cho idempotency, query tốt cho dashboard.  
  Áp dụng: phù hợp cả ingest transaction và nhu cầu tra cứu lọc/sắp xếp trên UI.

- **`S3 raw`**  
  Cơ chế: nhận payload lớn theo claim-check để tránh vượt hạn mức 256 KiB của SQS.  
  Áp dụng: message queue giữ pointer nhỏ, Lambda tự lấy object thật từ S3 khi xử lý.

- **`S3 exports`**  
  Cơ chế: Lambda ghi JSON snapshot sau ingest thành công theo prefix ngày.  
  Áp dụng: dashboard chỉ cần liệt kê object và cấp presigned URL tải trực tiếp.

- **`ALB`**  
  Cơ chế: load balancing + health check tách liveness/readiness.  
  Áp dụng: route traffic dashboard ổn định và cho phép giám sát health chuẩn hơn.

### Luồng dữ liệu end-to-end

- **Luồng chuẩn:** `Internet -> Worker -> SQS -> Lambda -> RDS`  
  Cơ chế: worker chỉ sản xuất message, Lambda mới là lớp ghi dữ liệu cuối cùng vào DB.  
  Áp dụng: giúp tách trách nhiệm, giảm coupling và dễ scale từng lớp.

- **Luồng payload lớn:** `Worker -> S3 raw -> SQS pointer -> Lambda -> RDS`  
  Cơ chế: claim-check pattern để giữ message nhỏ và ổn định queue latency.  
  Áp dụng: xử lý nguồn có nhiều bài hoặc summary dài mà không vỡ giới hạn SQS.

- **Luồng thủ công:** `Operator -> ALB -> POST /api/crawl -> run_once -> SQS -> Lambda -> RDS`  
  Cơ chế: trigger chạy nền và poll trạng thái, không chặn UI.  
  Áp dụng: phù hợp demo/vận hành bán tự động, kiểm soát thời điểm crawl theo nghiệp vụ.

---

## 3) Cơ chế crawl và lịch chạy

Hàm lõi crawl là `run_once()`: đọc config nguồn, crawl, chuẩn hóa article, gửi batch vào queue.

### Chế độ lịch (`CRAWLER_SCHEDULE_MODE`)

- **`interval`**  
  Cơ chế: APScheduler chạy định kỳ và có một lần chạy ngay sau khi boot để tránh “đợi chu kỳ đầu”.  
  Áp dụng: dùng cho môi trường muốn thu thập tự động liên tục với nhịp ổn định.

- **`once`**  
  Cơ chế: chạy đúng 1 cycle rồi thoát process, phù hợp mô hình cron hoặc test integration.  
  Áp dụng: tiện cho kiểm thử pipeline và tác vụ chạy theo lịch bên ngoài.

- **`idle`**  
  Cơ chế: worker không tự schedule; chỉ giữ process sống để quan sát/logging.  
  Áp dụng: dashboard trigger `POST /api/crawl` khi cần, tránh crawl thừa ở giai đoạn demo.

### Trạng thái demo hiện tại

- **`crawler_schedule_mode: idle`**  
  Cơ chế: cấu hình này được inject qua Ansible/systemd vào runtime container.  
  Áp dụng: team vận hành chủ yếu bấm “Crawl ngay” thay vì chạy timer tự động.

---

## 4) Mô hình dữ liệu và chống trùng

### Bảng `articles`

- **`source`**  
  Cơ chế: lưu nhãn nguồn (vd `rss:domain`, `sitemap:domain`) để phân tích theo kênh.  
  Áp dụng: dashboard lọc thống kê theo nguồn nhanh, rõ provenance dữ liệu.

- **`canonical_url` (UNIQUE)**  
  Cơ chế: dùng URL chuẩn hóa làm khóa nghiệp vụ duy nhất cho bài viết.  
  Áp dụng: chặn trùng xuyên suốt toàn pipeline kể cả khi nhiều worker cùng crawl.

- **`title`, `summary`**  
  Cơ chế: dữ liệu mềm (nullable), cho phép ingest thành công cả khi feed thiếu title.  
  Áp dụng: UI có `display_title` fallback từ summary/URL để không “mất thông tin hiển thị”.

- **`published_at`, `fetched_at`**  
  Cơ chế: tách thời điểm bài gốc và thời điểm hệ thống thu thập.  
  Áp dụng: phục vụ KPI freshness, lọc theo dải ngày và phân tích độ trễ ingest.

### Idempotency

- **`INSERT ... ON CONFLICT (canonical_url) DO NOTHING`**  
  Cơ chế: đưa logic chống trùng xuống tầng DB (atomic), tránh race-condition kiểu “check rồi insert”.  
  Áp dụng: retry bao nhiêu lần vẫn an toàn, không cần lock phân tán phức tạp ở worker.

---

## 5) SQS, Claim Check, và xử lý lỗi từng phần

### SQS cấu hình chính

- **Queue: `crawler-demo-data-queue` (Standard)**  
  Cơ chế: Standard ưu tiên throughput cao, chấp nhận at-least-once và best-effort ordering.  
  Áp dụng: phù hợp workload crawl vì đã có idempotency ở DB.

- **`VisibilityTimeout = 1080s`**  
  Cơ chế: ẩn message đủ dài so với Lambda timeout để tránh bị worker khác nhặt lại quá sớm.  
  Áp dụng: giảm duplicate xử lý trong lúc một invocation vẫn còn chạy.

- **`maxReceiveCount = 3` -> DLQ**  
  Cơ chế: cô lập message lỗi lặp khỏi luồng chính sau số lần retry giới hạn.  
  Áp dụng: vận hành dễ quan sát sự cố thật thay vì queue chính bị “kẹt”.

- **ESM (`batch_size=10`, `maximum_concurrency=5`, `ReportBatchItemFailures`)**  
  Cơ chế: batch tăng hiệu suất I/O; governor bảo vệ RDS; partial failure tránh fail cả lô.  
  Áp dụng: throughput vừa đủ cho Scope 1 nhưng vẫn kiểm soát rủi ro tài nguyên DB.

### Claim Check pattern

- **Payload <= `200 KiB` gửi thẳng SQS**  
  Cơ chế: ưu tiên đường đi ngắn cho batch nhỏ, giảm số call S3.  
  Áp dụng: đa số nguồn tin bình thường đi nhánh này để giảm latency.

- **Payload > `200 KiB` đưa vào S3 raw rồi gửi pointer**  
  Cơ chế: tách dữ liệu lớn khỏi queue, chỉ giữ metadata trong message.  
  Áp dụng: xử lý an toàn các nguồn có nội dung dài/nhiều item.

- **Lambda tự resolve pointer**  
  Cơ chế: consumer nhận biết kiểu payload (inline hay claim-check) và xử lý đồng nhất đầu ra.  
  Áp dụng: worker không phải gánh logic ingest phức tạp, trách nhiệm rõ ràng.

### Partial batch failure

- **`batchItemFailures` theo từng record**  
  Cơ chế: record thành công bị xóa ngay, record lỗi mới bị retry.  
  Áp dụng: tăng hiệu quả xử lý thực tế, tránh lặp lại cả batch chỉ vì một message lỗi.

---

## 6) Dashboard Web (FastAPI)

### API chính

- **`GET /health` (liveness)**  
  Cơ chế: chỉ kiểm tra app process còn sống, không đụng DB để tránh false negative.  
  Áp dụng: ALB dùng endpoint này để quyết định target healthy/unhealthy.

- **`GET /health/ready` (readiness)**  
  Cơ chế: thực thi `SELECT 1` kiểm tra kết nối DB thật.  
  Áp dụng: dùng cho monitor ngoài và status line trong UI.

- **`POST /api/crawl` + `GET /api/crawl/status`**  
  Cơ chế: chạy crawl nền bằng background task, có lock `_crawl_busy` chống chạy chồng.  
  Áp dụng: request thứ hai trả `409`, giúp vận hành không bấm đúp gây overrun.

- **`GET /api/articles`, `GET /api/articles/{id}`**  
  Cơ chế: hỗ trợ phân trang, sort, filter ngày, xem chi tiết bài.  
  Áp dụng: đáp ứng nghiệp vụ tra cứu và kiểm tra kết quả ingest nhanh.

- **`GET /api/stats`, `GET /api/sources`**  
  Cơ chế: gom KPI và danh mục nguồn từ DB để UI hiển thị tổng quan realtime.  
  Áp dụng: hỗ trợ đánh giá tình trạng crawl ngay trên dashboard.

- **`GET /api/s3/exports`, `GET /api/s3/exports/presign`**  
  Cơ chế: list object có phân trang + sinh presigned URL hết hạn.  
  Áp dụng: tải file export trực tiếp từ S3, không tiêu tốn băng thông EC2.

### Hành vi UI nổi bật

- **Poll trạng thái crawl sau khi bấm Crawl**  
  Cơ chế: frontend hỏi `/api/crawl/status` định kỳ cho đến khi `busy=false`.  
  Áp dụng: người dùng thấy tiến độ rõ, không cần refresh tay liên tục.

- **Nếu đang crawl -> request mới nhận `409`**  
  Cơ chế: lock ở backend là “single-flight” guard.  
  Áp dụng: ngăn chồng tác vụ crawl gây nhân đôi tải và nhiễu log.

- **Refresh nhiều nhịp sau crawl (4s/10s/20s)**  
  Cơ chế: chờ trễ tự nhiên của đường `SQS -> Lambda -> RDS` trước khi kết luận “không có dữ liệu mới”.  
  Áp dụng: giảm false alarm cho người vận hành khi ingest chưa kịp commit.

- **Export S3 presigned 1 giờ + “Lấy link mới”**  
  Cơ chế: sessionStorage lưu trạng thái đã tải để tránh dùng link hết hạn.  
  Áp dụng: UX rõ ràng hơn, giảm lỗi tải file do presign cũ.

---

## 7) Export dữ liệu S3

### Bucket exports

- **File do Lambda ghi sau ingest thành công**  
  Cơ chế: chỉ xuất snapshot khi đã có dữ liệu insert thực sự, đảm bảo tính nhất quán nghiệp vụ.  
  Áp dụng: file export phản ánh đúng các bài vừa ingest ở batch đó.

- **Định dạng `.json` UTF-8, có thụt dòng**  
  Cơ chế: ưu tiên tính đọc được (human-readable) và tương thích rộng.  
  Áp dụng: dễ kiểm tra tay trong báo cáo/demo, vẫn parse tốt cho pipeline phân tích.

- **Prefix `auto/` + key theo ngày `auto/YYYY/MM/DD/{uuid}_{n}.json`**  
  Cơ chế: partition theo ngày để list/retention/compliance thuận tiện.  
  Áp dụng: dashboard lọc prefix nhanh, vận hành truy vết theo ngày dễ.

- **Dashboard chỉ list + presign**  
  Cơ chế: tách quyền ghi/đọc; web không có logic tạo file export.  
  Áp dụng: giảm bề mặt lỗi và bề mặt tấn công cho lớp giao diện.

---

## 8) HA, Fault Tolerance, và các kịch bản lỗi

### Những điểm chống lỗi cốt lõi

- **ASG auto-healing EC2**  
  Cơ chế: health check fail thì ASG terminate và launch instance mới.  
  Áp dụng: giảm downtime worker/web khi host lỗi bất ngờ.

- **SQS lưu message tới khi xử lý xong**  
  Cơ chế: message chỉ bị xóa sau khi consumer xử lý thành công và ACK.  
  Áp dụng: bảo toàn dữ liệu đã vào queue dù compute layer gặp sự cố.

- **DLQ cô lập poison message**  
  Cơ chế: quá số lần nhận sẽ chuyển hàng đợi lỗi để phân tích root-cause.  
  Áp dụng: tránh “kẹt toàn tuyến” do một message lỗi lặp.

- **DB UNIQUE + upsert idempotent**  
  Cơ chế: lớp cuối cùng quyết định tính đúng dữ liệu, không phụ thuộc trạng thái retry trước đó.  
  Áp dụng: pipeline an toàn trong mọi kịch bản crash/replay.

### Kịch bản quan trọng

1. **Worker crash trước khi gửi SQS**  
   Cơ chế: dữ liệu mới crawl còn nằm trong RAM worker nên chưa bền vững.  
   Áp dụng: cycle đó có thể mất; mitigation là chạy cycle kế tiếp hoặc trigger tay lại.

2. **Worker crash sau khi gửi SQS**  
   Cơ chế: dữ liệu đã durable trong SQS nên tách khỏi vòng đời worker.  
   Áp dụng: Lambda vẫn ingest bình thường, không phụ thuộc worker còn sống hay không.

3. **Lambda crash trước commit**  
   Cơ chế: transaction rollback, message quay lại queue sau visibility timeout.  
   Áp dụng: hệ thống retry tự động, không để dữ liệu “nửa ghi”.

4. **Lambda crash sau commit nhưng trước ACK SQS**  
   Cơ chế: message bị phát lại nhưng DB bỏ qua do UNIQUE constraint.  
   Áp dụng: đảm bảo “không mất dữ liệu, không nhân bản dữ liệu”.

5. **Duplicate do nhiều worker cùng đẩy**  
   Cơ chế: chấp nhận duplicate ở queue để tối ưu đơn giản và độ tin cậy, chặn ở DB.  
   Áp dụng: tránh phải xây lock phân tán phức tạp ở Scope 1.

---

## 9) Scale và giới hạn hiện tại

### Scope 1 baseline

- **Worker ASG: `min=1, desired=1, max=2`**  
  Cơ chế: giữ baseline thấp để tiết kiệm, vẫn có headroom scale-out ngắn hạn.  
  Áp dụng: đủ cho tải hiện tại và demo ổn định.

- **Scale out CPU > 70%, scale in CPU < 40%**  
  Cơ chế: dùng alarm ngưỡng để mở/thu compute theo tải thực tế.  
  Áp dụng: tránh over-provision khi rảnh và under-provision khi spike.

- **Lambda ESM concurrency tối đa `5`**  
  Cơ chế: governor bảo vệ RDS khỏi bùng nổ kết nối.  
  Áp dụng: cân bằng giữa tốc độ ingest và ổn định DB.

- **RDS `db.t3.micro`, Single-AZ**  
  Cơ chế: tối ưu chi phí Scope 1, chấp nhận trade-off HA ở tầng DB.  
  Áp dụng: phù hợp bài lab; sản xuất thực nên nâng Multi-AZ ở Scope 2+.

### Nhận xét năng lực

- **Bottleneck thường là tần suất crawl**  
  Cơ chế: khi `idle`, thông lượng phụ thuộc số lần trigger thủ công, không phải scheduler.  
  Áp dụng: muốn tăng dữ liệu/ngày thì tăng nhịp trigger hoặc chuyển `interval`.

- **Pipeline ingest có đàn hồi tốt**  
  Cơ chế: SQS tách nhịp producer-consumer, Lambda tự scale trong khung an toàn.  
  Áp dụng: queue depth có thể tăng tạm thời mà không làm sập hệ thống.

- **Khi tăng tải ghi DB cần nâng kiến trúc**  
  Cơ chế: thêm RDS Proxy/DB class/read replica để giải quyết connection + throughput.  
  Áp dụng: roadmap rõ cho bước từ lab lên production lớn hơn.

---

## 10) Bảo mật và tuân thủ vận hành

- **KMS encryption cho RDS/SQS/S3/Secrets**  
  Cơ chế: mã hóa at-rest bằng CMK, giảm rủi ro lộ dữ liệu khi lưu trữ.  
  Áp dụng: tất cả lớp dữ liệu nhạy cảm trong bài đều có encryption thống nhất.

- **SQS policy TLS-only**  
  Cơ chế: từ chối request không dùng `aws:SecureTransport`.  
  Áp dụng: bắt buộc kênh truyền mã hóa khi gửi/nhận message.

- **Security Group least-privilege**  
  Cơ chế: chỉ mở đúng cổng/nguồn cần thiết giữa ALB, worker, Lambda, RDS.  
  Áp dụng: hạn chế lateral movement và giảm blast radius.

- **IMDSv2 bắt buộc cho EC2**  
  Cơ chế: harden metadata service chống một số kiểu SSRF credential theft.  
  Áp dụng: launch template đã set `http_tokens=required`.

- **Secrets Manager cho thông tin DB**  
  Cơ chế: tách secret khỏi source code, cấp phát runtime qua IaC/CM.  
  Áp dụng: tránh hardcode mật khẩu và thuận tiện rotation.

---

## 11) CI/CD và vận hành

### CI/CD

- **`test + terraform validate/plan`**  
  Cơ chế: chặn sớm lỗi code và drift IaC trước khi deploy.  
  Áp dụng: giảm rủi ro đẩy thay đổi hạ tầng không hợp lệ lên môi trường.

- **`build/push Docker image -> ECR`**  
  Cơ chế: chuẩn hóa artifact immutable theo commit SHA.  
  Áp dụng: rollback dễ, truy vết version rõ ràng.

- **`deploy Lambda code`**  
  Cơ chế: cập nhật function package độc lập với worker image.  
  Áp dụng: tối ưu tốc độ phát hành fix ingest mà không cần refresh cả ASG.

- **`ASG rolling instance refresh`**  
  Cơ chế: thay instance theo lô, giữ tỷ lệ healthy tối thiểu.  
  Áp dụng: deploy worker/web gần zero-downtime ở mức Scope 1.

### Runtime config

- **Terraform**  
  Cơ chế: quản lý trạng thái hạ tầng có kiểm soát bằng plan/apply.  
  Áp dụng: mọi resource AWS quan trọng đều có source-of-truth trong code.

- **Ansible**  
  Cơ chế: cấu hình runtime idempotent (service, env, Docker, tag image).  
  Áp dụng: thay đổi cấu hình nhanh mà không cần tạo lại hạ tầng từ đầu.

---

## 12) Kết luận kỹ thuật

Giải pháp hiện tại đạt mục tiêu Scope 1: kiến trúc tách lớp, chịu lỗi tốt, chống trùng chắc chắn, chi phí kiểm soát, dễ vận hành.

- **Điểm mạnh 1: pipeline bất đồng bộ `Worker -> SQS -> Lambda -> RDS`**  
  Cơ chế: tách nhịp xử lý giúp hấp thụ burst và giảm coupling giữa crawl/ingest.  
  Áp dụng: hệ thống vẫn chạy ổn ngay cả khi một lớp chậm tạm thời.

- **Điểm mạnh 2: idempotency ở DB**  
  Cơ chế: dùng unique key + upsert conflict handling ở lớp dữ liệu cuối.  
  Áp dụng: retry/crash không tạo duplicate, giảm mạnh độ phức tạp xử lý.

- **Điểm mạnh 3: dashboard hỗ trợ vận hành thủ công an toàn**  
  Cơ chế: lock chống double-trigger, poll trạng thái, phản hồi lỗi rõ ràng.  
  Áp dụng: phù hợp giai đoạn demo và giám sát thực nghiệm.

### Hướng nâng cấp Scope 2+ (production cao hơn)

- **RDS Multi-AZ + NAT đa AZ + HTTPS ALB** để nâng HA và bảo mật đường truyền.
- **RDS Proxy + nâng class DB + read replica** để tăng khả năng chịu tải ghi/đọc.
- **Mở rộng ASG/Lambda theo tải thực** với thêm alarm capacity planning và cost guardrails.

---

## 13) Assumptions (Giả định thiết kế)

- **Nguồn RSS/Sitemap hợp lệ phần lớn thời gian**  
  Cơ chế: pipeline hiện tại tối ưu cho nguồn trả về XML/Atom đúng chuẩn hoặc lỗi tạm thời có thể retry.  
  Áp dụng trong bài: parser không xây lớp “content recovery” quá sâu cho HTML hỏng nặng; nếu nguồn lỗi kéo dài thì đi vào nhánh vận hành (alert + điều tra).

- **Không yêu cầu strict ordering giữa các bài**  
  Cơ chế: dùng SQS Standard (best-effort ordering) thay vì FIFO để lấy throughput cao và chi phí thấp hơn.  
  Áp dụng: tính đúng dữ liệu dựa vào idempotency theo `canonical_url`, không dựa vào thứ tự message.

- **Mục tiêu chính là at-least-once + idempotent, không phải exactly-once**  
  Cơ chế: retry có thể làm message chạy lại, nhưng DB chặn trùng bằng unique key.  
  Áp dụng: đơn giản hóa kiến trúc Scope 1, tránh lock phân tán phức tạp.

- **Khối lượng ban đầu nằm trong năng lực `db.t3.micro`**  
  Cơ chế: giới hạn `maximum_concurrency=5` để bảo vệ budget kết nối và CPU DB.  
  Áp dụng: capacity hiện đủ cho lab/demo; khi tải tăng sẽ mở rộng theo roadmap Scope 2+.

---

## 14) Trade-offs (Đánh đổi kiến trúc)

- **Single-AZ RDS (tiết kiệm chi phí vs HA DB)**  
  Cơ chế: giảm chi phí cố định đáng kể nhưng chấp nhận rủi ro downtime cao hơn khi AZ lỗi.  
  Cách dùng trong bài: ưu tiên tính kinh tế Scope 1, bù bằng retry queue + alerting để giảm mất dữ liệu logic.

- **Single NAT Gateway (chi phí thấp vs SPOF egress)**  
  Cơ chế: chỉ một điểm NAT cho outbound nên rẻ hơn nhưng có rủi ro outage egress.  
  Cách dùng trong bài: chấp nhận trade-off giai đoạn đầu; giảm phần nào chi phí/áp lực NAT nhờ S3 Gateway Endpoint.

- **SQS Standard (throughput cao vs có thể duplicate/out-of-order)**  
  Cơ chế: tối ưu cho thông lượng, đổi lại phải xử lý duplicate ở tầng ứng dụng/dữ liệu.  
  Cách dùng trong bài: tận dụng `ON CONFLICT DO NOTHING` để hấp thụ duplicate an toàn.

- **Crawl mode `idle` (kiểm soát thủ công vs tự động hóa thấp hơn)**  
  Cơ chế: operator chủ động trigger, giảm crawl thừa nhưng tăng phụ thuộc thao tác con người.  
  Cách dùng trong bài: phù hợp demo/bảo vệ đề tài; production thực nên chuyển dần sang `interval` + policy lịch rõ ràng.

- **Không dùng distributed lock ở Scope 1 (đơn giản vận hành vs tốn xử lý duplicate)**  
  Cơ chế: bỏ lock giúp giảm độ phức tạp, nhưng có thể phát sinh message trùng khi scale worker.  
  Cách dùng trong bài: chấp nhận tăng compute nhẹ ở Lambda/DB để đổi lấy độ đơn giản và độ tin cậy triển khai.

---

## 15) Risks (Rủi ro vận hành chính)

- **RDS saturation (CPU cao / thiếu connections)**  
  Cơ chế: nếu queue tăng đột biến hoặc query dashboard nặng, DB nhỏ dễ thành bottleneck.  
  Dấu hiệu: `CPUUtilization` cao kéo dài, lỗi kết nối, latency ingest tăng.

- **Poison messages tăng trong DLQ**  
  Cơ chế: payload bất thường/lỗi parse có thể fail lặp cho đến khi vượt `maxReceiveCount`.  
  Dấu hiệu: alarm DLQ > 0, throughput thực giảm dù worker vẫn gửi queue đều.

- **Egress outage do NAT đơn**  
  Cơ chế: khi NAT gặp sự cố, worker không crawl nguồn ngoài và khó gọi API public cần outbound.  
  Dấu hiệu: crawl rỗng kéo dài, log network timeout đồng loạt từ worker.

- **Operational drift giữa Terraform và runtime thực tế**  
  Cơ chế: thay đổi tay trên instance hoặc config Ansible không phản ánh đầy đủ vào IaC.  
  Dấu hiệu: hành vi môi trường khác tài liệu, deploy mới gây “surprise changes”.

- **Tải tăng nhanh vượt giả định Scope 1**  
  Cơ chế: đột biến nguồn/tần suất crawl làm governor hiện tại không đủ cho SLA mới.  
  Dấu hiệu: queue depth tăng liên tục, thời gian từ crawl đến xuất hiện trên dashboard kéo dài.

---

## 16) Mitigations (Biện pháp giảm thiểu theo production mindset)

- **Guardrail cho DB và Lambda**  
  Cơ chế: giữ `maximum_concurrency` phù hợp budget DB, theo dõi sát `DatabaseConnections`, `RDS CPU`, `Lambda Errors`.  
  Áp dụng: nếu có dấu hiệu quá tải, giảm concurrency tạm thời trước, sau đó mới scale-up DB/proxy.

- **Runbook DLQ chuẩn hóa**  
  Cơ chế: quy trình 3 bước: inspect mẫu lỗi -> fix code/config -> redrive có tốc độ giới hạn.  
  Áp dụng: tránh redrive ồ ạt làm tái lỗi hàng loạt và gây bão retry.

- **Hardening triển khai mạng/HA theo từng pha**  
  Cơ chế: ưu tiên nâng Multi-AZ cho thành phần SPOF trước (RDS, NAT), sau đó mới tối ưu hiệu năng.  
  Áp dụng: roadmap rõ: `RDS Multi-AZ` -> `NAT đa AZ` -> `HTTPS ALB` để nâng độ sẵn sàng dần.

- **Quản trị thay đổi bằng IaC-first**  
  Cơ chế: mọi thay đổi hạ tầng đi qua Terraform plan/apply; runtime qua Ansible playbook có version control.  
  Áp dụng: giảm drift, tăng khả năng audit và rollback có kỷ luật.

- **Capacity planning định kỳ**  
  Cơ chế: review hàng tuần các chỉ số queue depth, ingest latency, DB load để điều chỉnh giới hạn trước khi nghẽn.  
  Áp dụng: chuyển từ phản ứng sự cố sang chủ động năng lực (predictive operations).

- **Bảo mật vận hành liên tục**  
  Cơ chế: rà soát IAM least-privilege, rotation secrets, giữ encrypt-at-rest + TLS-in-transit.  
  Áp dụng: giảm rủi ro lộ thông tin và đáp ứng yêu cầu audit cơ bản cho môi trường production.