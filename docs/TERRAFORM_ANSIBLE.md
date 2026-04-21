# Terraform & Ansible trong Crawler Project

## 1. Tại sao dùng cả Terraform và Ansible?

Trong hệ thống này, Terraform và Ansible không thay thế nhau mà bổ sung cho nhau:

- **Terraform** chịu trách nhiệm dựng hạ tầng cloud (AWS resources) theo mô hình IaC.
- **Ansible** chịu trách nhiệm cấu hình runtime trên EC2 (Docker, systemd, env vars, pull image).

Mô hình tách lớp này giúp hệ thống production-ready hơn vì:
- thay đổi hạ tầng và thay đổi cấu hình ứng dụng được quản trị độc lập;
- dễ kiểm soát rủi ro khi triển khai;
- giảm drift giữa thiết kế và vận hành thực tế.

---

## 2. Terraform — Lý thuyết và cơ chế

### 2.1 Terraform là gì?

Terraform là công cụ **declarative IaC**: bạn mô tả trạng thái mong muốn của hạ tầng, Terraform sẽ tính diff rồi áp dụng thay đổi để đạt trạng thái đó.

Điểm cốt lõi:
- có **state** (`tfstate`) để biết hạ tầng đã tạo;
- có vòng đời chuẩn: `init -> plan -> apply`;
- có thể module hóa để tái sử dụng kiến trúc.

### 2.2 Cơ chế hoạt động (ngắn gọn)

1. `terraform init` tải provider + backend.
2. `terraform plan` so config hiện tại với state để sinh execution plan.
3. `terraform apply` gọi AWS API tạo/sửa/xóa resource.
4. State được cập nhật lại làm nguồn sự thật cho lần chạy sau.

### 2.3 Cách dùng trong project này

Terraform đang provision các lớp chính:
- `modules/networking`: VPC, subnets, NAT, S3 endpoint
- `modules/security`: KMS, Secrets Manager, IAM, SG
- `modules/queue`: SQS main + DLQ
- `modules/storage`: RDS + S3 raw + S3 exports
- `modules/lambda`: Lambda ingester + ESM
- `modules/worker`: ECR + Launch Template + ASG
- `modules/observability`: SNS + alarms + dashboard
- `environments/demo/main.tf`: wiring module + ALB resources

### 2.4 Chuẩn production khi dùng Terraform

- Dùng **remote backend** (S3) + lock để tránh apply đồng thời.
- Bắt buộc review `plan` trước `apply`.
- Secrets không hardcode trong code repo.
- Ưu tiên module hóa để chuẩn hóa kiến trúc giữa các môi trường.

---

## 3. Ansible — Lý thuyết và cơ chế

### 3.1 Ansible là gì?

Ansible là công cụ configuration management theo hướng **idempotent**: chạy nhiều lần vẫn đưa máy về cùng trạng thái mục tiêu.

Phù hợp cho:
- cài package, cấu hình service;
- đồng bộ file cấu hình;
- triển khai/restart ứng dụng trên host đã có sẵn.

### 3.2 Cơ chế hoạt động (ngắn gọn)

1. Chọn host qua inventory (dynamic/static).
2. Playbook gọi roles theo thứ tự.
3. Mỗi task kiểm tra và chỉ đổi khi cần (idempotency).
4. Kết quả cuối: host khớp trạng thái chuẩn đã mô tả.

### 3.3 Cách dùng trong project này

Ansible chủ yếu chạy sau khi Terraform đã tạo xong hạ tầng:
- role `base`: gói hệ thống cơ bản
- role `docker`: cài/enable Docker
- role `cloudwatch_agent`: đẩy logs/metrics
- role `crawler_services`: pull image, render env, deploy/restart systemd services

File quan trọng:
- `infrastructure/ansible/playbooks/site.yml`
- `inventory/group_vars/crawler_demo/main.yml`
- `inventory/group_vars/crawler_demo/vault.yml` (secret)
- `roles/crawler_services/templates/*.j2`

### 3.4 Chuẩn production khi dùng Ansible

- Secrets để trong `ansible-vault`, không lộ plaintext.
- Inventory/tag strategy rõ ràng để không chạy nhầm host.
- Playbook phải idempotent, có thể chạy lại khi sự cố.
- Tách rõ thay đổi cấu hình runtime với thay đổi infra.

---

## 4. Terraform vs Ansible — khi nào dùng cái nào?

### Dùng Terraform khi:
- tạo/sửa AWS resources (RDS, SQS, ASG, IAM, SG, ALB...)
- thay đổi topology mạng hoặc scaling envelope
- cần output hạ tầng cho các lớp khác sử dụng

### Dùng Ansible khi:
- đổi image tag, env vars, schedule mode trên EC2
- restart/redeploy service mà không muốn recreate instance
- chuẩn hóa runtime hiện trường sau bootstrap user_data

### Không nên:
- dùng Ansible để “đẻ” tài nguyên AWS lõi thay Terraform (dễ drift)
- dùng Terraform cho các thao tác runtime lặp hàng ngày trên host (chậm và kém linh hoạt)

---

## 5. Quy trình triển khai khuyến nghị trong bài

1. **Terraform apply** để dựng hạ tầng nền.
2. Push Docker image lên **ECR**.
3. (Nếu cần) init schema qua Lambda.
4. **Ansible playbook** để đồng bộ runtime worker/web.
5. Kiểm tra health endpoint + CloudWatch + queue/DB metrics.

Luồng này giúp:
- giảm rủi ro deploy;
- có thể rollback theo từng lớp;
- dễ kiểm soát thay đổi khi demo hoặc nâng lên production.

---

## 6. Các lỗi thực tế hay gặp và cách tránh

- **Terraform drift**: chỉnh tay trên console -> lần apply sau gây bất ngờ.  
  -> Quy ước IaC-first, hạn chế manual changes.

- **Ansible SSH/SSM lỗi key/inventory**: host discover được nhưng không vào được máy.  
  -> Đồng bộ `worker_ec2_key_name`, `.pem`, `group_vars/connection.yml`.

- **Config lệch giữa Terraform outputs và Ansible vars**: app chạy sai queue/bucket/DB host.  
  -> Dùng script render vars từ Terraform outputs và review trước khi chạy playbook.

---

## 7. Kết luận kiến trúc vận hành

Với scope hiện tại, cách kết hợp **Terraform (infra) + Ansible (runtime)** là lựa chọn đúng production mindset:
- rõ trách nhiệm từng lớp;
- an toàn khi thay đổi;
- dễ mở rộng khi chuyển Scope 2+ (HA cao hơn, security chặt hơn, automation sâu hơn).

Nói ngắn gọn:  
**Terraform dựng “nền móng”, Ansible giữ “vận hành ổn định” trên nền đó.**
