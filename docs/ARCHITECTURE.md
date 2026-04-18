# AWS Web Crawler - Production Architecture (Scope 1)

## Muc luc
1. Scope bai toan chi tiet cu the den tung truong hop cua bai toan
2. Kien truc tong quan
3. Data Flow - Luong du lieu End-to-End
4. Phan tich tung Service
5. Networking & Security
6. Infrastructure as Code (Terraform)
7. CI/CD Pipeline
8. Capacity Planning & Toan hoc cau hinh
9. High Availability & Fault Tolerance
10. Observability & Monitoring
11. Production Checklist

## 1. Scope bai toan chi tiet cu the den tung truong hop cua bai toan

### 1.1 Muc tieu Scope 1
- Xay dung he thong thu thap noi dung web theo mo hinh tach roi: `EC2 Worker -> SQS Standard -> Lambda Ingester -> RDS + S3`.
- Uu tien tinh on dinh, idempotency, khong mat du lieu, va kiem soat chi phi.
- Dat "production-ready" ngay tu pham vi nho, khong doi den Scope sau moi bo sung co che van hanh.

### 1.2 Loai du lieu dau vao
- RSS feed (`crawl_rss`): lay link bai viet, title, summary, pubDate.
- Sitemap (`crawl_sitemap`): ho tro ca `urlset` va `sitemapindex` long nhau.
- Moi URL duoc canonicalize truoc khi dua vao queue de giam duplicate som.

### 1.3 Truong hop xu ly chinh
- **Truong hop A - Payload nho**: Worker serialize truc tiep danh sach bai viet vao SQS message body.
- **Truong hop B - Payload lon**: Worker kich hoat Claim Check, nen gzip -> upload S3 raw -> gui pointer S3 qua SQS.
- **Truong hop C - Duplicate URL**: RDS unique index + `ON CONFLICT DO NOTHING` dam bao ghi de khong nhan ban.
- **Truong hop D - Loi tam thoi**: Lambda fail record nao chi retry record do (`ReportBatchItemFailures`).
- **Truong hop E - Poison message**: sau 3 lan nhan that bai, message vao DLQ de dieu tra.

### 1.4 Out-of-scope cho Scope 1
- Chua trien khai API phuc vu query public.
- Chua su dung RDS Proxy/read replica.
- Chua multi-region active-active.

## 2. Kien truc tong quan

```text
┌──────────────────┐   Crawl + Normalize   ┌──────────────┐   Event Source    ┌────────────────┐
│  EC2 ASG Worker  │──────────────────────▶│ SQS Standard │───────────────────▶│ Lambda Ingester│
│  min=1 max=2     │                       │ VT=1080, DLQ │                    │ batch=10, maxESM=5│
└──────┬───────────┘                       └──────────────┘                    └──────┬─────────┘
       │ Claim Check (> threshold)                                                       │ UPSERT
       ▼                                                                                  ▼
┌──────────────┐                                                                  ┌──────────────┐
│ S3 raw bucket│                                                                  │ RDS Postgres │
│ (gzip html)  │                                                                  │ db.t3.micro  │
└──────────────┘                                                                  └──────────────┘
       │
       └──────────────► S3 exports bucket (csv/json)
```

Nguyen tac cot loi:
- Producer/consumer decoupled bang queue ben vung.
- Idempotency dat tai tang DB (nguon chan duplicate cuoi cung).
- Concurrency duoc gioi hanh co chu dich de bao ve RDS.

## 3. Data Flow - Luong du lieu End-to-End

### Buoc 1 - Worker crawl
1. APScheduler trigger chu ky crawl.
2. Worker goi RSS/Sitemap qua `httpx`.
3. Parse record, canonicalize URL, cat summary theo gioi han.
4. Tao `ArticleIn` list.

### Buoc 2 - Worker day message
1. Serialize list sang JSON bytes.
2. Neu vuot `claim_check_threshold_bytes`: gzip + upload `s3://raw/...` + tao pointer.
3. Gui message vao SQS Standard (batch API).

### Buoc 3 - Lambda consume
1. SQS event mapping day toi 10 records/invocation.
2. Moi record:
   - Neu body la pointer Claim Check thi fetch + gunzip tu S3.
   - Parse thanh list article.
3. Dung mot DB connection cho toan invocation.

### Buoc 4 - Persist idempotent
1. Chay `INSERT ... ON CONFLICT (canonical_url) DO NOTHING`.
2. Record thanh cong bi xoa khoi SQS.
3. Record that bai duoc tra ve trong `batchItemFailures` de retry.

### Buoc 5 - Failure routing
- Qua 3 lan fail, SQS tu dong chuyen vao DLQ.
- Alarm DLQ > 0 gui SNS email.

## 4. Phan tich tung Service

### 4.1 EC2 Auto Scaling Worker
- **Scale profile**: `t3.micro`, `desired=1`, `min=1`, `max=2`.
- **Policy**:
  - Scale out +1 neu CPU > 70% trong 3 phut.
  - Scale in -1 neu CPU < 40% trong 3 phut.
- **Process safety**: APScheduler `max_instances=1`, `coalesce=True`.
- **Bootstrapping**: user-data cai Docker, pull image tu ECR, chay bang `systemd`.

### 4.2 SQS Standard + DLQ
- **Visibility timeout 1080s** tranh message bi xu ly song song khi Lambda cham.
- **DLQ maxReceiveCount=3** de tach poison message.
- **Long polling** giam empty receive.
- **TLS-only policy** (`DenyNonSecureTransport`) + KMS encryption.

### 4.3 Lambda Ingester
- **Batch size=10** can bang throughput va rollback granularity.
- **SQS event-source max concurrency=5** gioi han tai dong thoi o tang event source mapping.
- **Reserved concurrency** de `null` mac dinh trong demo de tranh vuot quota account.
- **Partial failure semantics**: chi retry record loi.
- **DB interaction**:
  - 1 ket noi/invocation.
  - Khong SELECT check duplicate.
  - Ghi de atomic bang `ON CONFLICT DO NOTHING`.

### 4.4 RDS PostgreSQL
- `db.t3.micro`, Single-AZ cho Scope 1.
- Bang `articles` co unique index tren `canonical_url`.
- Dong vai tro "source of truth" cho du lieu da chuan hoa.

### 4.5 S3 (raw + exports)
- **raw bucket**: luu payload Claim Check, lifecycle expiration.
- **exports bucket**: luu file csv/json cho downstream usage.
- Ca hai bucket bat KMS + block public access.

## 5. Networking & Security

### 5.1 Networking
- VPC tach 3 lop subnet: `public`, `private`, `db` tren >=2 AZ.
- Worker va Lambda chay private subnet.
- RDS dat db subnet, khong public endpoint.
- S3 Gateway Endpoint giam luong qua NAT, toi uu chi phi.

### 5.2 Security Groups
- SG Worker: outbound toi internet/SQS/S3 theo route.
- SG Lambda: outbound toi RDS/S3/SQS.
- SG RDS: chi allow 5432 tu SG Lambda.

### 5.3 IAM va Secret
- IAM role rieng cho Worker va Lambda (least privilege).
- Secret DB trong Secrets Manager, ma hoa KMS.
- Enforce IMDSv2 tren launch template.

### 5.4 Data protection
- Encryption at rest: SQS, S3, RDS deu dung KMS.
- Encryption in transit: TLS policy cho SQS, ket noi HTTPS toi AWS APIs.

## 6. Infrastructure as Code (Terraform)

Cau truc module:
- `networking`: VPC, subnet, route, NAT, endpoint.
- `security`: KMS, IAM, SG, Secrets.
- `queue`: SQS main + DLQ + policy.
- `storage`: RDS + S3 buckets + lifecycle.
- `worker`: ECR, Launch Template, ASG, scaling alarms.
- `lambda`: function, role binding, SQS event mapping.
- `observability`: CW alarms, dashboard, SNS notifications.

Moi truong `environments/demo` wire output-input giua modules theo pattern:
- Networking -> Security/Worker/Lambda/Storage
- Security -> Worker/Lambda/Storage/Queue
- Queue -> Worker (producer), Lambda (consumer)
- Storage -> Worker (raw bucket), Lambda (DB endpoint + secret)

Nguyen tac IaC ap dung:
- Reusable module, bien ro rang, output day du.
- Default an toan cho Scope 1, mo rong bang variable (khong can rewrite module).

## 7. CI/CD Pipeline

### 7.1 Muc tieu
- Tu dong validate code + Terraform truoc khi deploy.
- Build image worker on-demand, day ECR, rollout ASG co kiem soat.

### 7.2 De xuat pipeline toi thieu
1. **Lint/Test stage**
   - `python -m py_compile ...`
   - `pytest`
   - `terraform fmt -check`
   - `terraform validate`
2. **Build stage**
   - Build Docker worker image.
   - Tag theo commit SHA.
3. **Publish stage**
   - Push image len ECR.
4. **Deploy stage**
   - `terraform apply` cho ha tang.
   - Trigger ASG `start-instance-refresh`.
5. **Post-deploy verify**
   - Kiem tra CloudWatch alarms/dashboard.
   - Smoke test crawl 1 chu ky.

### 7.3 Co che rollback
- Terraform: rollback bang git revert + apply lai.
- Worker image: re-point tag stable va refresh ASG.
- Lambda: rollback alias/version (neu ap dung versioning).

## 8. Capacity Planning & Toan hoc cau hinh

### 8.1 Lambda va RDS connection budget
- RDS `db.t3.micro` thuong co gioi han ket noi xap xi 66.
- Scope demo gioi han bang `maximum_concurrency = 5` o SQS event source mapping de on dinh tren account quota nho.
- Neu account du quota, co the bat `reserved_concurrency` de hard-cap theo budget DB.

Cong thuc tham khao:
- `max_lambda_concurrency <= db_max_connections * safety_factor`
- Chon `safety_factor ~ 0.7-0.8`.

### 8.2 Visibility timeout math
- Rule: `visibility_timeout >= 6 * lambda_timeout`.
- Scope 1: `lambda_timeout=180s` => `VT=1080s`.
- Muc dich: tranh duplicate processing khi retry/network jitter.

### 8.3 Queue throughput
- Lambda moi invocation xu ly toi da 10 message.
- Throughput ly thuyet:
  - `records_per_sec ~= active_invocations * 10 / avg_duration_sec`.
- Voi `maximum_concurrency = 5`:
  - Neu avg 2s/batch => ~25 records/s (ly thuyet, tru hao retry/IO).

### 8.4 Worker capacity
- ASG 1-2 node.
- 1 node du cho traffic nen.
- Node thu 2 chi kich hoat khi CPU sustained cao, tranh overprovision.

## 9. High Availability & Fault Tolerance

### 9.1 Hien trang Scope 1
- Worker layer HA theo Multi-AZ ASG.
- Queue ben vung, tach loi producer/consumer.
- Lambda managed service, tu scale trong gioi han concurrency.
- RDS Single-AZ (diem SPOF duoc chap nhan cho Scope 1 vi chi phi).

### 9.2 Co che chong loi
- Retry co kiem soat tai SQS/Lambda.
- DLQ co lap poison message.
- Idempotent write tranh duplicate khi retry.
- Claim Check tranh vuot gioi han message va giam loi payload lon.

### 9.3 Huong nang cap Scope 2+
- Bat RDS Multi-AZ.
- Them RDS Proxy khi concurrency cao.
- Backup/restore drill dinh ky.

## 10. Observability & Monitoring

### 10.1 Logging
- Worker logs -> CloudWatch Logs (qua CW Agent).
- Lambda logs -> CloudWatch Logs.
- Cung dinh dang log de trace theo `trace_id` neu can.

### 10.2 Metrics canh bao cot loi
- SQS: ApproximateNumberOfMessagesVisible, AgeOfOldestMessage.
- DLQ: message visible > 0 (critical).
- Lambda: Errors, Throttles, Duration, ConcurrentExecutions.
- RDS: CPUUtilization, DatabaseConnections, FreeStorageSpace.
- ASG/EC2: CPUUtilization, InServiceInstances.

### 10.3 Alarm strategy
- DLQ > 0: canh bao ngay.
- Lambda Errors vuot nguong theo cua so 5 phut.
- RDS CPU > 80% lien tuc.
- ASG = max size trong thoi gian dai (bao hieu can scale policy/re-arch).

### 10.4 Dashboard
- Gom 1 man hinh tong hop: Queue health, Ingestion health, DB health, Worker health.
- Muc tieu: on-call vao la thay ngay bottleneck nam o dau.

## 11. Production Checklist

### 11.1 Truoc deploy
- [ ] Dien day du `terraform.tfvars` (account, region, db_password, alert_email).
- [ ] ECR image build thanh cong, tag ro rang.
- [ ] `terraform validate` pass.
- [ ] Schema `articles` da duoc apply, unique index ton tai.

### 11.2 Trong deploy
- [ ] `terraform apply` thanh cong, khong co drift bat thuong.
- [ ] ASG instance refresh da duoc trigger sau khi push image moi.
- [ ] Lambda env vars/secret mapping dung endpoint RDS va queue URL.

### 11.3 Sau deploy
- [ ] Worker crawl duoc, SQS depth bien dong binh thuong.
- [ ] Lambda consume duoc, khong tang loi bat thuong.
- [ ] RDS co insert moi, khong duplicate do conflict handling.
- [ ] DLQ bang 0 hoac da co quy trinh replay.
- [ ] Dashboard va SNS alert hoat dong.

### 11.4 Van hanh dinh ky
- [ ] Review IAM permissions theo quy.
- [ ] Kiem tra chi phi NAT/S3/Lambda/RDS hang tuan.
- [ ] Chay game day nho: mo phong fail Lambda, fail worker, replay DLQ.
