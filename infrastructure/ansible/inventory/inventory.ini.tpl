# Generated from Terraform outputs + local SSH settings.
# Render via:
#   infrastructure/ansible/scripts/render-runtime-from-terraform.sh

[crawler_demo]
worker-1 ansible_host=${ansible_worker_host}

[crawler_demo:vars]
ansible_user=${ansible_user}
ansible_ssh_private_key_file=${ansible_ssh_private_key_file}
%{ if ansible_bastion_host != "" ~}
ansible_ssh_common_args='-o ProxyJump=${ansible_bastion_user}@${ansible_bastion_host}'
%{ endif ~}

# Runtime variables used by roles
crawler_aws_region=${aws_region}
crawler_ecr_repo_url=${crawler_ecr_repo_url}
crawler_cwa_log_group_name=${crawler_cwa_log_group_name}
crawler_sqs_queue_url=${crawler_sqs_queue_url}
crawler_s3_raw_bucket=${crawler_s3_raw_bucket}
crawler_s3_exports_bucket=${crawler_s3_exports_bucket}
crawler_web_db_host=${crawler_db_host}
crawler_web_db_port=${crawler_db_port}
crawler_web_db_name=${crawler_db_name}
crawler_web_db_user=${crawler_db_user}
crawler_web_port=8080
crawler_image_tag=latest
crawler_schedule_mode=interval
crawler_interval_seconds=1800
crawler_max_items_per_source=100
crawler_claim_check_threshold_bytes=204800
crawler_log_level=INFO
monitoring_grafana_port=3000
monitoring_grafana_admin_user=admin
monitoring_grafana_admin_password=admin123!
monitoring_webapp_metrics_host=host.docker.internal
