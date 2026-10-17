resource "aws_kms_key" "main" {
  description             = "${var.name} data, secrets, images and logs"
  enable_key_rotation     = true
  deletion_window_in_days = 30
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Sid = "AccountAdministration", Effect = "Allow", Principal = { AWS = "arn:aws:iam::${var.account_id}:root" }, Action = "kms:*", Resource = "*" },
    { Sid       = "EncryptedLogs", Effect = "Allow", Principal = { Service = "logs.${var.region}.amazonaws.com" },
      Action    = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:DescribeKey"], Resource = "*",
      Condition = { ArnLike = { "kms:EncryptionContext:aws:logs:arn" = ["arn:aws:logs:${var.region}:${var.account_id}:log-group:/ecs/${var.name}/*", "arn:aws:logs:${var.region}:${var.account_id}:log-group:/aws/rds/instance/${var.name}/postgresql"] } }
    }
  ] })
}
resource "aws_kms_alias" "main" {
  name          = "alias/${var.name}"
  target_key_id = aws_kms_key.main.key_id
}
resource "random_password" "secret" {
  for_each = toset(["django", "database", "broker", "reviewer"])
  length   = 48
  special  = false
}
resource "aws_secretsmanager_secret" "app" {
  for_each                = toset(["django", "database", "broker", "reviewer"])
  name                    = "${var.name}/${each.key}"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = 30
}
resource "aws_secretsmanager_secret_version" "app" {
  for_each      = aws_secretsmanager_secret.app
  secret_id     = each.value.id
  secret_string = random_password.secret[each.key].result
}
resource "aws_cloudwatch_log_group" "service" {
  for_each          = local.roles
  name              = "/ecs/${var.name}/${each.key}"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.main.arn
  skip_destroy      = true
}
resource "aws_cloudwatch_log_group" "database" {
  name              = "/aws/rds/instance/${var.name}/postgresql"
  retention_in_days = 30
  kms_key_id        = aws_kms_key.main.arn
  skip_destroy      = true
}
resource "aws_db_subnet_group" "main" {
  name       = var.name
  subnet_ids = [for subnet in aws_subnet.private : subnet.id]
}
resource "aws_db_parameter_group" "main" {
  name_prefix = "${var.name}-"
  family      = "postgres17"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}
resource "aws_db_instance" "main" {
  identifier                      = var.name
  engine                          = "postgres"
  engine_version                  = var.postgres_engine_version
  instance_class                  = var.database_instance_class
  allocated_storage               = 100
  max_allocated_storage           = 200
  storage_type                    = "gp3"
  storage_encrypted               = true
  kms_key_id                      = aws_kms_key.main.arn
  db_name                         = "resume_match"
  username                        = "resume_admin"
  manage_master_user_password     = true
  master_user_secret_kms_key_id   = aws_kms_key.main.arn
  db_subnet_group_name            = aws_db_subnet_group.main.name
  parameter_group_name            = aws_db_parameter_group.main.name
  vpc_security_group_ids          = [aws_security_group.database.id]
  publicly_accessible             = false
  multi_az                        = true
  backup_retention_period         = 7
  backup_window                   = "03:00-04:00"
  maintenance_window              = "sun:04:00-sun:05:00"
  copy_tags_to_snapshot           = true
  deletion_protection             = var.deletion_protection
  skip_final_snapshot             = false
  final_snapshot_identifier       = coalesce(var.final_snapshot_identifier, "${var.name}-final")
  enabled_cloudwatch_logs_exports = ["postgresql"]
  auto_minor_version_upgrade      = true
  depends_on                      = [aws_cloudwatch_log_group.database]
}
resource "aws_mq_broker" "main" {
  broker_name                = var.name
  engine_type                = "RabbitMQ"
  engine_version             = "4.3"
  host_instance_type         = var.mq_instance_type
  deployment_mode            = "CLUSTER_MULTI_AZ"
  subnet_ids                 = [for subnet in aws_subnet.private : subnet.id]
  security_groups            = [aws_security_group.broker.id]
  publicly_accessible        = false
  auto_minor_version_upgrade = true
  encryption_options {
    kms_key_id        = aws_kms_key.main.arn
    use_aws_owned_key = false
  }
  user {
    username = "resume_broker"
    password = random_password.secret["broker"].result
  }
  maintenance_window_start_time {
    day_of_week = "SUNDAY"
    time_of_day = "05:00"
    time_zone   = "UTC"
  }
}
resource "aws_ecr_repository" "image" {
  for_each             = toset(["api", "web"])
  name                 = "${var.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  image_scanning_configuration {
    scan_on_push = true
  }
  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = aws_kms_key.main.arn
  }
}
