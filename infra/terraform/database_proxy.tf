locals {
  proxy_users = { app = "resume_app", stream = "resume_stream" }
  proxy_roles = toset(["app", "worker", "relay", "gateway", "event-relay"])
}
resource "random_password" "stream_database" {
  length  = 48
  special = false
}
resource "aws_secretsmanager_secret" "proxy" {
  for_each                = local.proxy_users
  name                    = "${var.name}/proxy-${each.key}"
  kms_key_id              = aws_kms_key.main.arn
  recovery_window_in_days = 30
}
resource "aws_secretsmanager_secret_version" "proxy" {
  for_each      = local.proxy_users
  secret_id     = aws_secretsmanager_secret.proxy[each.key].id
  secret_string = jsonencode({ username = each.value, password = each.key == "app" ? random_password.secret["database"].result : random_password.stream_database.result })
}
resource "aws_iam_role" "database_proxy" {
  name               = "${var.name}-database-proxy"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Principal = { Service = "rds.amazonaws.com" }, Action = "sts:AssumeRole" }] })
}
resource "aws_iam_role_policy" "database_proxy" {
  name = "read-two-database-credentials"
  role = aws_iam_role.database_proxy.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = [for secret in aws_secretsmanager_secret.proxy : secret.arn] },
    { Effect = "Allow", Action = ["kms:Decrypt"], Resource = aws_kms_key.main.arn,
    Condition = { StringEquals = { "kms:ViaService" = "secretsmanager.${var.region}.amazonaws.com" }, StringLike = { "kms:EncryptionContext:SecretARN" = [for secret in aws_secretsmanager_secret.proxy : secret.arn] } } }
  ] })
}
resource "aws_security_group" "database_proxy" {
  name_prefix = "${var.name}-proxy-"
  vpc_id      = aws_vpc.main.id
}
resource "aws_db_proxy" "main" {
  name                   = "${var.name}-database"
  engine_family          = "POSTGRESQL"
  default_auth_scheme    = "NONE"
  require_tls            = true
  debug_logging          = false
  idle_client_timeout    = 300
  role_arn               = aws_iam_role.database_proxy.arn
  vpc_subnet_ids         = [for subnet in aws_subnet.private : subnet.id]
  vpc_security_group_ids = [aws_security_group.database_proxy.id]
  dynamic "auth" {
    for_each = local.proxy_users
    content {
      auth_scheme               = "SECRETS"
      secret_arn                = aws_secretsmanager_secret.proxy[auth.key].arn
      iam_auth                  = "DISABLED"
      client_password_auth_type = "POSTGRES_SCRAM_SHA_256"
    }
  }
  depends_on = [aws_iam_role_policy.database_proxy, aws_secretsmanager_secret_version.proxy]
}
resource "aws_db_proxy_default_target_group" "main" {
  db_proxy_name = aws_db_proxy.main.name
  connection_pool_config {
    connection_borrow_timeout    = 2
    max_connections_percent      = 50
    max_idle_connections_percent = 10
    # PostgreSQL role defaults supply timeout/timezone state; no pinning filter.
  }
}
resource "aws_db_proxy_target" "main" {
  db_proxy_name          = aws_db_proxy.main.name
  target_group_name      = aws_db_proxy_default_target_group.main.name
  db_instance_identifier = aws_db_instance.main.identifier
}
resource "aws_vpc_security_group_ingress_rule" "proxy_client" {
  for_each                     = local.proxy_roles
  security_group_id            = aws_security_group.database_proxy.id
  referenced_security_group_id = aws_security_group.task[each.key].id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_egress_rule" "proxy_client" {
  for_each                     = local.proxy_roles
  security_group_id            = aws_security_group.task[each.key].id
  referenced_security_group_id = aws_security_group.database_proxy.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_ingress_rule" "proxy_database" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.database_proxy.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_egress_rule" "proxy_database" {
  security_group_id            = aws_security_group.database_proxy.id
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
