locals {
  definitions = var.image_digests == null ? toset([]) : local.roles
  services    = var.image_digests == null ? toset([]) : toset(["app", "relay", "worker"])
  api_image   = var.image_digests == null ? null : "${aws_ecr_repository.image["api"].repository_url}@${var.image_digests.api}"
  web_image   = var.image_digests == null ? null : "${aws_ecr_repository.image["web"].repository_url}@${var.image_digests.web}"
  environment = {
    DJANGO_DEBUG                = "false"
    DJANGO_ALLOWED_HOSTS        = var.hostname
    DJANGO_CSRF_TRUSTED_ORIGINS = "https://${var.hostname}"
    DJANGO_TRUST_PROXY          = "true"
    POSTGRES_HOST               = aws_db_instance.main.address
    POSTGRES_PORT               = "5432"
    POSTGRES_DB                 = "resume_match"
    POSTGRES_USER               = "resume_app"
    POSTGRES_SSLMODE            = "verify-full"
    POSTGRES_SSLROOTCERT        = "/app/certs/rds-global-bundle.pem"
    RABBITMQ_HOST               = replace(replace(aws_mq_broker.main.instances[0].endpoints[0], "amqps://", ""), ":5671", "")
    RABBITMQ_USER               = "resume_broker"
    RABBITMQ_TLS                = "true"
    MATCH_PROVIDER              = "bedrock"
    AWS_REGION                  = var.region
    BEDROCK_MODEL_ID            = var.bedrock_model_id
    AWS_EC2_METADATA_DISABLED   = "true"
    DOCUMENT_BUCKET             = aws_s3_bucket.originals.id
    DOCUMENT_REGION             = var.region
    DOCUMENT_SCAN_MODE          = "guardduty"
    DOCUMENT_RETENTION_DAYS     = tostring(var.document_retention_days)
  }
  secret_environment = {
    DJANGO_SECRET_KEY = aws_secretsmanager_secret.app["django"].arn
    POSTGRES_PASSWORD = aws_secretsmanager_secret.app["database"].arn
  }
  commands = {
    app       = ["gunicorn", "config.wsgi:application", "--bind", "127.0.0.1:8000", "--workers", "2", "--threads", "2", "--timeout", "60", "--access-logfile", "/dev/null", "--error-logfile", "-"]
    relay     = ["python", "manage.py", "relay_jobs"]
    worker    = ["celery", "-A", "config", "worker", "--loglevel=WARNING", "--concurrency=1", "--without-gossip", "--without-mingle"]
    bootstrap = ["python", "manage.py", "bootstrap_cloud_db"]
  }
  health_commands = {
    app       = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/',timeout=3)"]
    relay     = ["CMD", "python", "-c", "import pathlib,time; assert time.time()-pathlib.Path('/tmp/resume-match-relay-heartbeat').stat().st_mtime<15"]
    worker    = ["CMD", "python", "-c", "import os,pathlib; os.kill(int(pathlib.Path('/tmp/resume-match-worker-ready').read_text()),0)"]
    bootstrap = ["CMD", "true"]
  }
  api_containers = { for role in local.definitions : role => {
    name        = "api", image = local.api_image, essential = true,
    command     = local.commands[role], readonlyRootFilesystem = true,
    user        = "10001:10001", linuxParameters = { initProcessEnabled = true, capabilities = { drop = ["ALL"] } },
    mountPoints = [{ sourceVolume = "api-tmp", containerPath = "/tmp", readOnly = false }],
    environment = [for name, value in merge(local.environment, { LAB_SERVICE_NAME = role == "app" ? "api" : role }, role == "bootstrap" ? { CLOUD_REVIEWER_USERNAME = var.reviewer_username } : {}) : { name = name, value = value }],
    secrets = [for name, value in merge(local.secret_environment,
      contains(["relay", "worker"], role) ? { RABBITMQ_PASSWORD = aws_secretsmanager_secret.app["broker"].arn } : {},
      role == "bootstrap" ? {
        RDS_MASTER_USERNAME     = "${aws_db_instance.main.master_user_secret[0].secret_arn}:username::",
        RDS_MASTER_PASSWORD     = "${aws_db_instance.main.master_user_secret[0].secret_arn}:password::",
        CLOUD_REVIEWER_PASSWORD = aws_secretsmanager_secret.app["reviewer"].arn
    } : {}) : { name = name, valueFrom = value }],
    healthCheck      = { command = local.health_commands[role], interval = 15, timeout = 5, retries = 3, startPeriod = 30 },
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.service[role].name, awslogs-region = var.region, awslogs-stream-prefix = "api", mode = "non-blocking", max-buffer-size = "1m" } }
  } }
  web_container = {
    name             = "web", image = local.web_image, essential = true, readonlyRootFilesystem = true,
    portMappings     = [{ containerPort = 8080, hostPort = 8080, protocol = "tcp" }],
    dependsOn        = [{ containerName = "api", condition = "HEALTHY" }],
    environment      = [{ name = "FRONTEND_API_UPSTREAM", value = "127.0.0.1:8000" }, { name = "FRONTEND_TRUST_ALB_PROTO", value = "true" }],
    linuxParameters  = { initProcessEnabled = true, capabilities = { drop = ["ALL"] } },
    mountPoints      = [{ sourceVolume = "web-tmp", containerPath = "/tmp", readOnly = false }],
    healthCheck      = { command = ["CMD", "wget", "-q", "--spider", "http://127.0.0.1:8080/"], interval = 15, timeout = 5, retries = 3, startPeriod = 30 },
    logConfiguration = { logDriver = "awslogs", options = { awslogs-group = aws_cloudwatch_log_group.service["app"].name, awslogs-region = var.region, awslogs-stream-prefix = "web", mode = "non-blocking", max-buffer-size = "1m" } }
  }
}
resource "aws_ecs_cluster" "main" {
  name = var.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}
resource "aws_ecs_task_definition" "service" {
  for_each                 = local.definitions
  family                   = "${var.name}-${each.key}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = contains(["app", "worker"], each.key) ? "1024" : "512"
  memory                   = contains(["app", "worker"], each.key) ? "2048" : "1024"
  execution_role_arn       = aws_iam_role.execution[each.key].arn
  task_role_arn            = aws_iam_role.task[each.key].arn
  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }
  dynamic "volume" {
    for_each = each.key == "app" ? toset(["api-tmp", "web-tmp"]) : toset(["api-tmp"])
    content {
      name = volume.value
    }
  }
  container_definitions = jsonencode(concat([local.api_containers[each.key]], each.key == "app" ? [local.web_container] : []))
  depends_on            = [aws_iam_role_policy.execution, aws_secretsmanager_secret_version.app, aws_iam_role_policy.documents, aws_guardduty_malware_protection_plan.originals]
}
resource "aws_ecs_service" "main" {
  for_each                           = local.services
  name                               = "${var.name}-${each.key}"
  cluster                            = aws_ecs_cluster.main.id
  task_definition                    = aws_ecs_task_definition.service[each.key].arn
  desired_count                      = var.enable_services ? (each.key == "relay" ? 1 : 2) : 0
  launch_type                        = "FARGATE"
  platform_version                   = "1.4.0"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = each.key == "app" ? 60 : null
  availability_zone_rebalancing      = "ENABLED"
  enable_execute_command             = false
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }
  network_configuration {
    subnets          = [for subnet in aws_subnet.private : subnet.id]
    security_groups  = [aws_security_group.task[each.key].id]
    assign_public_ip = false
  }
  dynamic "load_balancer" {
    for_each = each.key == "app" ? [1] : []
    content {
      target_group_arn = aws_lb_target_group.app.arn
      container_name   = "web"
      container_port   = 8080
    }
  }
  lifecycle {
    precondition {
      condition     = !var.enable_services || aws_guardduty_malware_protection_plan.originals.status == "ACTIVE"
      error_message = "Do not enable admission or processing until document malware protection reports ACTIVE."
    }
  }
  depends_on = [aws_lb_listener.https, aws_vpc_endpoint.service, aws_vpc_endpoint.bedrock, aws_vpc_endpoint.s3_layers, aws_iam_role_policy.bedrock]
}
