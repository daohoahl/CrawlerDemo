# =============================================================================
# MODULE: worker
#
# Creates:
#   - ECR repository (holds the worker Docker image)
#   - Launch Template for EC2 t3.micro running the container via Docker
#   - Auto Scaling Group spanning Multi-AZ private subnets
#   - CloudWatch CPU-based scaling policies
#   - CloudWatch Log Group for systemd/container logs
#
# Spec alignment (Scope 1):
#   - Instance type t3.micro (Free Tier)
#   - ASG: desired=1, min=1, max=2  (HA with cost control)
#   - Multi-AZ (>= 2 AZs — enforced by networking module)
#   - Scale out: CPUUtilization > 70 % for 3 minutes (3 × 60 s periods)
#   - Scale in : CPUUtilization < 40 % for 3 minutes
# =============================================================================

locals {
  name_prefix = "${var.project}-${var.environment}"
  tags        = merge(var.common_tags, { Module = "worker" })
}

# ── ECR Repository (worker image) ────────────────────────────────────────────

resource "aws_ecr_repository" "worker" {
  name                 = "${local.name_prefix}-worker"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = merge(local.tags, { Name = "${local.name_prefix}-worker" })
}

resource "aws_ecr_lifecycle_policy" "worker" {
  repository = aws_ecr_repository.worker.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# ── CloudWatch Log Group for the worker ──────────────────────────────────────

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ec2/${local.name_prefix}-worker"
  retention_in_days = var.log_retention_days
  tags              = merge(local.tags, { Name = "${local.name_prefix}-worker-logs" })
}

# ── Latest Amazon Linux 2023 AMI ─────────────────────────────────────────────

data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-2023.*-kernel-6.1-x86_64"]
  }

  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

# ── User data: install Docker, pull image, run with systemd ──────────────────

locals {
  user_data = base64encode(templatefile("${path.module}/templates/user_data.sh.tpl", {
    aws_region                  = var.aws_region
    ecr_repo_url                = aws_ecr_repository.worker.repository_url
    log_group_name              = aws_cloudwatch_log_group.worker.name
    sqs_queue_url               = var.sqs_queue_url
    s3_raw_bucket               = var.s3_raw_bucket
    s3_exports_bucket           = var.s3_exports_bucket
    interval_seconds            = var.interval_seconds
    max_items_per_source        = var.max_items_per_source
    claim_check_threshold_bytes = var.claim_check_threshold_bytes
    web_db_host                 = var.web_db_host
    web_db_port                 = var.web_db_port
    web_db_name                 = var.web_db_name
    web_db_user                 = var.web_db_user
    web_db_password             = var.web_db_password
    web_port                    = var.web_port
  }))
}

# ── Launch Template ──────────────────────────────────────────────────────────

resource "aws_launch_template" "worker" {
  name_prefix   = "${local.name_prefix}-worker-"
  image_id      = data.aws_ami.al2023.id
  instance_type = var.instance_type

  iam_instance_profile {
    name = var.iam_instance_profile_name
  }

  vpc_security_group_ids = [var.sg_worker_id]

  # Enforce IMDSv2 (security best practice)
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  monitoring {
    enabled = true # 1-minute CloudWatch metrics (needed for responsive scaling)
  }

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size           = 8
      volume_type           = "gp3"
      delete_on_termination = true
      encrypted             = true
    }
  }

  user_data = local.user_data

  tag_specifications {
    resource_type = "instance"
    tags = merge(local.tags, {
      Name = "${local.name_prefix}-worker"
      Role = "crawler-worker"
    })
  }

  tag_specifications {
    resource_type = "volume"
    tags          = merge(local.tags, { Name = "${local.name_prefix}-worker-vol" })
  }

  tags = merge(local.tags, { Name = "${local.name_prefix}-worker-lt" })
}

# ── Auto Scaling Group (Multi-AZ) ───────────────────────────────────────────

resource "aws_autoscaling_group" "worker" {
  name                      = "${local.name_prefix}-worker-asg"
  vpc_zone_identifier       = var.private_subnet_ids # Spec: Multi-AZ (>=2 subnets)
  min_size                  = var.min_size           # Spec: 1
  max_size                  = var.max_size           # Spec: 2
  desired_capacity          = var.desired_capacity   # Spec: 1
  health_check_type         = "EC2"
  health_check_grace_period = 300
  default_cooldown          = 180

  launch_template {
    id      = aws_launch_template.worker.id
    version = "$Latest"
  }

  # Rolling replacement when the Launch Template changes
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
      instance_warmup        = 120
    }
  }

  tag {
    key                 = "Name"
    value               = "${local.name_prefix}-worker"
    propagate_at_launch = true
  }

  dynamic "tag" {
    for_each = local.tags
    content {
      key                 = tag.key
      value               = tag.value
      propagate_at_launch = true
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

# ═════════════════════════════════════════════════════════════════════════════
# Scaling Policies — CPU-based (spec: > 70 % scale-out, < 40 % scale-in)
# ═════════════════════════════════════════════════════════════════════════════

# ── Scale-OUT policy: add +1 instance ───────────────────────────────────────
resource "aws_autoscaling_policy" "scale_out" {
  name                   = "${local.name_prefix}-scale-out"
  autoscaling_group_name = aws_autoscaling_group.worker.name
  scaling_adjustment     = 1
  adjustment_type        = "ChangeInCapacity"
  cooldown               = 180
}

resource "aws_cloudwatch_metric_alarm" "cpu_high" {
  alarm_name          = "${local.name_prefix}-worker-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3  # 3 consecutive periods
  period              = 60 # 60-second periods (=> 3 minutes total)
  threshold           = 70 # spec
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  statistic           = "Average"
  treat_missing_data  = "notBreaching"

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.worker.name
  }

  alarm_actions = [aws_autoscaling_policy.scale_out.arn]

  tags = merge(local.tags, { Name = "${local.name_prefix}-worker-cpu-high" })
}

# ── Scale-IN policy: remove -1 instance ─────────────────────────────────────
resource "aws_autoscaling_policy" "scale_in" {
  name                   = "${local.name_prefix}-scale-in"
  autoscaling_group_name = aws_autoscaling_group.worker.name
  scaling_adjustment     = -1
  adjustment_type        = "ChangeInCapacity"
  cooldown               = 180
}

resource "aws_cloudwatch_metric_alarm" "cpu_low" {
  alarm_name          = "${local.name_prefix}-worker-cpu-low"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 3  # 3 consecutive periods
  period              = 60 # 60-second periods (=> 3 minutes total)
  threshold           = 40 # spec
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  statistic           = "Average"
  treat_missing_data  = "notBreaching"

  dimensions = {
    AutoScalingGroupName = aws_autoscaling_group.worker.name
  }

  alarm_actions = [aws_autoscaling_policy.scale_in.arn]

  tags = merge(local.tags, { Name = "${local.name_prefix}-worker-cpu-low" })
}
