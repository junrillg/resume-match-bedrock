locals {
  definitions = var.image_digests == null ? toset([]) : local.roles
  services    = var.image_digests == null ? toset([]) : toset(["app", "relay", "worker", "gateway", "event-relay"])
  api_image   = var.image_digests == null ? null : "${aws_ecr_repository.image["api"].repository_url}@${var.image_digests.api}"
  web_image   = var.image_digests == null ? null : "${aws_ecr_repository.image["web"].repository_url}@${var.image_digests.web}"
  environment = {
    DJANGO_DEBUG                     = "false"
    DJANGO_ALLOWED_HOSTS             = var.hostname
    DJANGO_CSRF_TRUSTED_ORIGINS      = "https://${var.hostname}"
    DJANGO_TRUST_PROXY               = "true"
    POSTGRES_HOST                    = aws_db_proxy.main.endpoint
    POSTGRES_PORT                    = "5432"
    POSTGRES_DB                      = "resume_match"
    POSTGRES_USER                    = "resume_app"
    POSTGRES_SSLMODE                 = "verify-full"
    POSTGRES_SSLROOTCERT             = "/app/certs/amazon-trust-services.pem"
    POSTGRES_PROXY_MODE              = "true"
    APP_DB_CONNECTION_LIMIT          = tostring(var.app_db_connection_limit)
    STREAM_DB_CONNECTION_LIMIT       = tostring(var.stream_db_connection_limit)
    GLOBAL_ADMISSION_PER_SECOND      = tostring(var.admission_rate_per_second)
    QUEUE_AGE_LIMIT_SECONDS          = tostring(var.queue_age_limit_seconds)
    GLOBAL_ADMISSION_MAX_ACTIVE      = tostring(var.admission_max_active)
    OWNER_ACTIVE_JOB_LIMIT           = tostring(var.owner_active_job_limit)
    ADMISSION_HEALTH_MAX_AGE_SECONDS = tostring(var.admission_health_max_age_seconds)
    STREAM_REDIS_TLS                 = "true"
    RABBITMQ_HOST                    = replace(replace(aws_mq_broker.main.instances[0].endpoints[0], "amqps://", ""), ":5671", "")
    RABBITMQ_USER                    = "resume_broker"
    RABBITMQ_TLS                     = "true"
    MATCH_PROVIDER                   = "bedrock"
    AWS_REGION                       = var.region
    BEDROCK_MODEL_ID                 = var.bedrock_model_id
    AWS_EC2_METADATA_DISABLED        = "true"
    DOCUMENT_BUCKET                  = aws_s3_bucket.originals.id
    DOCUMENT_REGION                  = var.region
    DOCUMENT_SCAN_MODE               = "guardduty"
    DOCUMENT_RETENTION_DAYS          = tostring(var.document_retention_days)
  }
  secret_environment = {
    DJANGO_SECRET_KEY = aws_secretsmanager_secret.app["django"].arn
    POSTGRES_PASSWORD = aws_secretsmanager_secret.app["database"].arn
  }
  commands = {
    app         = ["gunicorn", "config.wsgi:application", "--bind", "127.0.0.1:8000", "--workers", "2", "--threads", "2", "--timeout", "60", "--access-logfile", "/dev/null", "--error-logfile", "-"]
    relay       = ["python", "manage.py", "relay_jobs"]
    worker      = ["celery", "-A", "config", "worker", "--loglevel=WARNING", "--concurrency=1", "--without-gossip", "--without-mingle"]
    bootstrap   = ["python", "manage.py", "bootstrap_cloud_db"]
    gateway     = ["uvicorn", "event_gateway:application", "--host", "0.0.0.0", "--port", "8001", "--no-access-log", "--log-level", "warning", "--timeout-graceful-shutdown", "25"]
    event-relay = ["python", "manage.py", "relay_events"]
  }
  health_commands = {
    app         = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health/',timeout=3)"]
    relay       = ["CMD", "python", "-c", "import pathlib,time; assert time.time()-pathlib.Path('/tmp/resume-match-relay-heartbeat').stat().st_mtime<15"]
    worker      = ["CMD", "python", "-c", "import os,pathlib; os.kill(int(pathlib.Path('/tmp/resume-match-worker-ready').read_text()),0)"]
    bootstrap   = ["CMD", "true"]
    gateway     = ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health/',timeout=3)"]
    event-relay = ["CMD", "python", "-c", "import pathlib,time; assert time.time()-pathlib.Path('/tmp/resume-match-event-relay-heartbeat').stat().st_mtime<15"]
  }
  role_environment = { for role in local.roles : role => merge(local.environment,
    { LAB_SERVICE_NAME = role == "app" ? "api" : role },
    role == "bootstrap" ? {
      POSTGRES_HOST           = aws_db_instance.main.address,
      POSTGRES_PROXY_MODE     = "false",
      POSTGRES_SSLROOTCERT    = "/app/certs/rds-global-bundle.pem",
      CLOUD_REVIEWER_USERNAME = var.reviewer_username
    } : {},
    role == "gateway" ? {
      POSTGRES_USER                = "resume_stream",
      STREAM_GATEWAY_PROCESS       = "true",
      STREAM_DB_WORKERS            = tostring(var.gateway_db_workers),
      STREAM_DB_QUEUE              = "64",
      STREAM_MAX_CONNECTIONS       = tostring(var.gateway_connections),
      STREAM_MAX_OWNER_CONNECTIONS = "5",
      DELIVERY_CLOUD_METRICS       = "true",
      ECS_SERVICE_NAME             = "${var.name}-gateway"
    } : {},
    contains(["gateway", "event-relay"], role) ? {
      STREAM_REDIS_HOSTS    = local.fanout_hosts,
      STREAM_REDIS_USERNAME = role == "gateway" ? "gateway" : "relay"
  } : {}) }
  api_containers = { for role in local.definitions : role => {
    name         = "api", image = local.api_image, essential = true,
    command      = local.commands[role], readonlyRootFilesystem = true,
    user         = "10001:10001", linuxParameters = { initProcessEnabled = true, capabilities = { drop = ["ALL"] } },
    mountPoints  = [{ sourceVolume = "api-tmp", containerPath = "/tmp", readOnly = false }],
    environment  = [for name, value in local.role_environment[role] : { name = name, value = value }],
    portMappings = role == "gateway" ? [{ containerPort = 8001, hostPort = 8001, protocol = "tcp" }] : [],
    stopTimeout  = 30,
    ulimits      = role == "gateway" ? [{ name = "nofile", softLimit = 10000, hardLimit = 10000 }] : [],
    secrets = [for name, value in merge(local.secret_environment,
      contains(["relay", "worker"], role) ? { RABBITMQ_PASSWORD = aws_secretsmanager_secret.app["broker"].arn } : {},
      role == "gateway" ? { POSTGRES_PASSWORD = "${aws_secretsmanager_secret.proxy["stream"].arn}:password::" } : {},
      contains(["gateway", "event-relay"], role) ? { STREAM_REDIS_PASSWORD = aws_secretsmanager_secret.fanout[role == "gateway" ? "gateway" : "relay"].arn } : {},
      role == "bootstrap" ? {
        STREAM_DB_PASSWORD      = "${aws_secretsmanager_secret.proxy["stream"].arn}:password::",
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
    environment      = [{ name = "FRONTEND_API_UPSTREAM", value = "127.0.0.1:8000" }, { name = "FRONTEND_TRUST_ALB_PROTO", value = "true" }, { name = "FRONTEND_EVENTS_TRANSPORT", value = "alb" }],
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
  desired_count                      = var.enable_services ? var.service_capacity[each.key].min : 0
  launch_type                        = "FARGATE"
  platform_version                   = "1.4.0"
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200
  health_check_grace_period_seconds  = contains(["app", "gateway"], each.key) ? 60 : null
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
    for_each = contains(["app", "gateway"], each.key) ? [1] : []
    content {
      target_group_arn = each.key == "gateway" ? aws_lb_target_group.gateway.arn : aws_lb_target_group.app.arn
      container_name   = each.key == "gateway" ? "api" : "web"
      container_port   = each.key == "gateway" ? 8001 : 8080
    }
  }
  lifecycle {
    ignore_changes = [desired_count]
    precondition {
      condition     = !var.enable_services || aws_guardduty_malware_protection_plan.originals.status == "ACTIVE"
      error_message = "Do not enable admission or processing until document malware protection reports ACTIVE."
    }
  }
  depends_on = [terraform_data.capacity, aws_lb_listener_rule.events, aws_db_proxy_target.main, aws_vpc_endpoint.service, aws_vpc_endpoint.bedrock, aws_vpc_endpoint.s3_layers, aws_iam_role_policy.bedrock]
}
