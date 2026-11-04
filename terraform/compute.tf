resource "aws_launch_template" "worker" {
  name_prefix   = "payments-worker-${var.environment}-"
  image_id      = data.aws_ami.al2023_arm64.id
  instance_type = var.worker_instance_type

  vpc_security_group_ids = [aws_security_group.worker.id]

  block_device_mappings {
    device_name = "/dev/xvda"
    ebs {
      volume_size = var.worker_root_volume_gb
      volume_type = "gp3"
      encrypted   = true
    }
  }

  metadata_options {
    http_tokens = "required"
  }
}

resource "aws_autoscaling_group" "worker" {
  name                = "payments-worker-${var.environment}"
  min_size            = 2
  max_size            = 6
  desired_capacity    = var.worker_desired_capacity
  vpc_zone_identifier = var.db_subnet_ids
  target_group_arns   = [aws_lb_target_group.api.arn]

  health_check_type         = "ELB"
  health_check_grace_period = 120

  launch_template {
    id      = aws_launch_template.worker.id
    version = "$Latest"
  }
}

# Scratch volumes, one per worker, attached by a boot script.
resource "aws_ebs_volume" "scratch" {
  count             = var.scratch_volume_count
  availability_zone = data.aws_availability_zones.available.names[count.index % 2]
  size              = 100
  type              = "gp3"
  encrypted         = true
  tags              = { Name = "payments-scratch-${count.index}" }
}

resource "aws_lb" "api" {
  name               = "payments-api-${var.environment}"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb.id]
  subnets            = var.public_subnet_ids

  enable_deletion_protection = true
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "api" {
  name     = "payments-api-${var.environment}"
  port     = 8080
  protocol = "HTTP"
  vpc_id   = var.vpc_id

  health_check {
    path                = "/health"
    healthy_threshold   = 2
    unhealthy_threshold = 3
    interval            = 30
  }
}

resource "aws_lb_listener" "api" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}
