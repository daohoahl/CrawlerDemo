# Generated runtime environment for CI / Ansible bootstrap.
# Render this file via:
#   infrastructure/ansible/scripts/render-runtime-from-terraform.sh

AWS_REGION=${aws_region}
AWS_ACCOUNT_ID=${aws_account_id}
ENVIRONMENT=${environment}
PROJECT=${project}

# Terraform outputs
CRAWLER_ECR_REPO_URL=${crawler_ecr_repo_url}
CRAWLER_WEB_URL=${crawler_web_url}
CRAWLER_SQS_QUEUE_URL=${crawler_sqs_queue_url}
CRAWLER_S3_RAW_BUCKET=${crawler_s3_raw_bucket}
CRAWLER_S3_EXPORTS_BUCKET=${crawler_s3_exports_bucket}
CRAWLER_DB_HOST=${crawler_db_host}
CRAWLER_DB_PORT=${crawler_db_port}
CRAWLER_DB_NAME=${crawler_db_name}
CRAWLER_DB_USER=${crawler_db_user}
CRAWLER_WORKER_ASG_NAME=${crawler_worker_asg_name}

# Ansible SSH settings (local/runtime)
ANSIBLE_GROUP=${ansible_group}
ANSIBLE_USER=${ansible_user}
ANSIBLE_SSH_PRIVATE_KEY_FILE=${ansible_ssh_private_key_file}
ANSIBLE_BASTION_USER=${ansible_bastion_user}
ANSIBLE_BASTION_HOST=${ansible_bastion_host}
ANSIBLE_WORKER_HOST=${ansible_worker_host}
