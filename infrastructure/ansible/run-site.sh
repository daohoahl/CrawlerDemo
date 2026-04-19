#!/usr/bin/env bash
# Chạy playbook từ đúng thư mục Ansible + workaround macOS (tránh "worker dead state" với SSM).
set -euo pipefail
cd "$(dirname "$0")"
if ansible --version 2>/dev/null | grep -qiE 'python version.*3\.(1[3-9]|[2-9][0-9])'; then
  echo "[cảnh báo] Ansible đang chạy trên Python 3.13+; với SSM dễ lỗi NoneType. Dùng: ./run-site-venv.sh" >&2
fi
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
exec ansible-playbook playbooks/site.yml "$@"
