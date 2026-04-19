# Ansible — cấu hình worker EC2 (Amazon Linux 2023)

Playbook này triển khai **cùng một lớp cấu hình** như `user_data.sh.tpl` trong Terraform: Docker, CloudWatch Agent, hai container (`crawler-worker`, FastAPI `crawler-web`) và service chuyển log ra `/var/log/crawler.log`.

Dùng khi bạn muốn:

- chỉnh sửa cấu hình **không** đổi Launch Template / ASG refresh;
- tái lập máy từ AMI hoặc máy thử nghiệm (không chạy lại toàn bộ user-data);
- chuẩn hóa bước vận hành (idempotent, có diff).

## Chuẩn bị

1. Terraform đã `apply` (có ECR, SQS, S3, RDS, log group).
2. **Ansible → worker:** dùng **SSH qua Session Manager** (`AWS-StartSSHSession`), **không** dùng plugin `amazon.aws.aws_ssm` (tránh lỗi `NoneType` trên máy điều khiển). Cấu hình trong `inventory/group_vars/crawler_demo/connection.yml` (cùng thư mục cha với file inventory động — Ansible mới load được `group_vars`).
3. **Key pair (bắt buộc cho SSH):** trong Terraform đặt `worker_ec2_key_name` = tên Key Pair đã có trong EC2 (cùng region), `terraform apply` rồi để ASG thay instance mới có public key. File `.pem` tương ứng giữ trên máy chạy Ansible.
4. **Khuyến nghị:** venv Python 3.11/3.12 (`./run-site-venv.sh`) thay cho `brew install ansible` (Python 3.14).
5. `ansible-galaxy collection install -r collections/requirements.yml` (script venv tự chạy) — inventory động vẫn cần plugin `amazon.aws.aws_ec2`.
6. AWS credentials trên máy local (`aws configure` / `AWS_PROFILE`) — inventory gọi `ec2:DescribeInstances`; lệnh `aws ssm start-session` trong ProxyCommand cần `ssm:StartSession`.

## Inventory (quan trọng)

- **ASG / Instance ID đổi:** **`inventory/crawler_worker.aws_ec2.yml`** (đuôi **`*.aws_ec2.yml`**). Lọc `running` + tag `Role=crawler-worker`, `Environment=demo`. **Không** dùng `hostvars_prefix` (dễ làm `ansible_host` sai → SSM lỗi `NoneType`). Cảnh báo `tags` reserved có thể bỏ qua. `ansible-galaxy collection install -r collections/requirements.yml`. IAM: `ec2:DescribeInstances`.
- **Một ID cố định (debug):** `inventory/demo-ssm.yml` với `ansible_host: i-...`.
- File inventory **phải tên `*.yml`** — không dùng `*.yml.example` làm `-i` (Ansible parse sai → không có host).
- **SSH / bastion:** `inventory/examples/demo.yml.ssh.example` → `inventory/demo.yml` và `-i inventory/demo.yml`.
- Nếu đổi **environment** Terraform (không còn `demo`), sửa filter `tag:Environment` trong `crawler_worker.aws_ec2.yml`.

## Biến

1. Điền inventory như trên (SSM hoặc SSH).
2. Điền `inventory/group_vars/crawler_demo/main.yml` — có thể sinh phần lớn từ Terraform:

```bash
chmod +x scripts/render-vars-from-terraform.sh
./scripts/render-vars-from-terraform.sh
```

3. Mật khẩu DB: `cp inventory/group_vars/crawler_demo/vault.yml.example inventory/group_vars/crawler_demo/vault.yml`, sửa giá trị, rồi `ansible-vault encrypt inventory/group_vars/crawler_demo/vault.yml`.

## Chạy

**Luôn đứng đúng thư mục:** repo gốc `Crawler` thì `cd infrastructure/ansible`; nếu đã thấy `pwd` là `.../infrastructure/ansible` thì **không** `cd infrastructure/ansible` lần nữa (sẽ báo `no such file`).

**macOS:** nếu gặp `A worker was found in a dead state` khi dùng SSM, chạy script (đã set `OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES`) hoặc export biến đó rồi gọi `ansible-playbook` như bình thường.

```bash
cd /path/to/Crawler/infrastructure/ansible
chmod +x run-site-venv.sh
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
# Đường tới .pem trùng Key Pair trong Terraform (worker_ec2_key_name):
./run-site-venv.sh --ask-vault-pass -e ansible_ssh_private_key_file=$HOME/.ssh/crawler-worker.pem

# Nếu không dùng venv (brew ansible):
./run-site.sh --ask-vault-pass -e ansible_ssh_private_key_file=$HOME/.ssh/crawler-worker.pem
```

**Lưu ý:** Session Manager plugin (`session-manager-plugin`) phải có trong `PATH` (cùng lệnh `aws ssm start-session` đã dùng được).

**macOS / OpenSSH:** nếu thấy `Could not resolve hostname i-...`, inventory đã đặt `ansible_host: 127.0.0.1` và dùng `{{ inventory_hostname }}` (instance id) trong `ProxyCommand` — không để ssh cố resolve `i-...` như tên DNS.

**AWS CLI trong ProxyCommand:** nếu thấy `the following arguments are required: command` khi kết nối, nguyên nhân thường là chuỗi `ansible_ssh_common_args` bị `shlex.split()` tách sai — toàn bộ `ProxyCommand=aws ssm ...` phải nằm trong một cặp dấu ngoặc kép (đã cấu hình trong `inventory/group_vars/crawler_demo/connection.yml`).

**Kiểm tra biến host / vault:** `ansible-inventory` cũng đọc `vault.yml`; dùng `ansible-inventory --ask-vault-pass --host i-...` (hoặc `--vault-password-file`) thay vì chỉ `ansible-inventory --host ...`.

**`Permission denied (publickey)`:** Tunnel SSM đã tới được sshd trên worker (`ec2-user@127.0.0.1`), nhưng máy EC2 không chấp nhận khóa bạn gửi.

1. **Terraform đã gắn key pair chưa?** Biến `worker_ec2_key_name` **mặc định là `null`** — khi đó Launch Template **không** đặt key, instance **không có** public key trong `authorized_keys` → mọi `.pem` đều bị từ chối. Trong **EC2 → Instances**, xem cột **Key pair** (hoặc chi tiết instance). Nếu trống: thêm vào `terraform.tfvars` dòng `worker_ec2_key_name = "TenKeyPairTrongConsole"` (đúng **tên** key pair trong region, không phải đường dẫn file), chạy `terraform apply`, rồi **thay instance** (ASG instance refresh / terminate để ASG tạo máy mới theo LT mới).
2. Truyền private key khi chạy Ansible: `-e ansible_ssh_private_key_file=/đường/dẫn/crawler_admin.pem` (file `.pem` tải lúc tạo **cùng** key pair ở bước 1).
3. Sau khi đổi key trên LT, instance **cũ** vẫn không có key — bắt buộc máy **mới** từ ASG.
4. `chmod 600` cho file `.pem`.
5. Có thể `ssh-add ~/.ssh/...pem` rồi chạy playbook không cần `-e` nếu agent giữ đúng khóa.

Chỉ kiểm tra cú pháp:

```bash
ansible-playbook playbooks/site.yml --syntax-check
```

## Ghi chú

- Instance profile EC2 cần quyền `ecr:GetAuthorizationToken` và pull image (đã cấu hình trong Terraform).
- Playbook **restart** cả ba service systemd ở cuối — phù hợp triển khai có chủ đích, tránh chạy liên tục trên máy đang phục vụ nếu không cần.
- **`NoneType` với SSM**: dùng `./run-site-venv.sh` (Python 3.11/3.12); cài gói trên máy remote bằng `raw`/`command` + `dnf` trong các role.

### `CERTIFICATE_VERIFY_FAILED` khi `ansible-galaxy`

Thường gặp trên macOS (venv không tìm thấy CA). **`run-site-venv.sh`** đã export `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` từ gói **`certifi`** sau khi `pip install`.

Tự xử lý tay (trước mọi lệnh `ansible-galaxy`):

```bash
pip install certifi
export SSL_CERT_FILE="$(python3 -c 'import certifi; print(certifi.where())')"
export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"
```

Nếu cài Python từ **python.org**, chạy **`Install Certificates.command`** trong thư mục Python. Môi trường công ty (proxy SSL) có thể cần thêm CA nội bộ vào trust store — không tắt xác thực SSL trừ khi hiểu rủi ro.
