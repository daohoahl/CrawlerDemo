#!/usr/bin/env bash
# Chạy Ansible trong venv Python ổn định (khuyến nghị khi brew install ansible dùng Python 3.14 → lỗi SSM NoneType).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

PY=""
for try in python3.12 python3.11 python3.10; do
  if command -v "$try" &>/dev/null; then PY="$try"; break; fi
done
if [[ -z "$PY" ]]; then
  echo "Cần python3.12 hoặc python3.11 (brew install python@3.12)." >&2
  exit 1
fi

if [[ ! -d .venv ]]; then
  "$PY" -m venv .venv
fi
# shellcheck source=/dev/null
source .venv/bin/activate
python -m pip install -q -U pip
pip install -q -r requirements-controller.txt

# macOS / venv: tránh CERTIFICATE_VERIFY_FAILED khi gọi galaxy.ansible.com
export SSL_CERT_FILE="$(python -c 'import certifi; print(certifi.where())')"
export REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"

ansible-galaxy collection install -r collections/requirements.yml

export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
exec ansible-playbook playbooks/site.yml "$@"
