locals {
  task_trust = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "ecs-tasks.amazonaws.com" }, Action = "sts:AssumeRole",
    Condition = { StringEquals = { "aws:SourceAccount" = var.account_id }, ArnLike = { "aws:SourceArn" = "arn:aws:ecs:${var.region}:${var.account_id}:*" } }
  }] })
  secret_access = {
    app         = [aws_secretsmanager_secret.app["django"].arn, aws_secretsmanager_secret.app["database"].arn]
    relay       = [aws_secretsmanager_secret.app["django"].arn, aws_secretsmanager_secret.app["database"].arn, aws_secretsmanager_secret.app["broker"].arn]
    worker      = [aws_secretsmanager_secret.app["django"].arn, aws_secretsmanager_secret.app["database"].arn, aws_secretsmanager_secret.app["broker"].arn]
    bootstrap   = [aws_secretsmanager_secret.app["django"].arn, aws_secretsmanager_secret.app["database"].arn, aws_secretsmanager_secret.app["reviewer"].arn, aws_db_instance.main.master_user_secret[0].secret_arn, aws_secretsmanager_secret.proxy["stream"].arn]
    gateway     = [aws_secretsmanager_secret.app["django"].arn, aws_secretsmanager_secret.proxy["stream"].arn, aws_secretsmanager_secret.fanout["gateway"].arn]
    event-relay = [aws_secretsmanager_secret.app["django"].arn, aws_secretsmanager_secret.app["database"].arn, aws_secretsmanager_secret.fanout["relay"].arn]
  }
}
resource "aws_iam_role" "execution" {
  for_each           = local.roles
  name               = "${var.name}-${each.key}-execution"
  assume_role_policy = local.task_trust
}
resource "aws_iam_role_policy" "execution" {
  for_each = local.roles
  name     = "startup"
  role     = aws_iam_role.execution[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["ecr:GetAuthorizationToken"], Resource = "*" },
    { Effect = "Allow", Action = ["ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer", "ecr:BatchGetImage"], Resource = each.key == "app" ? [aws_ecr_repository.image["api"].arn, aws_ecr_repository.image["web"].arn] : [aws_ecr_repository.image["api"].arn] },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.service[each.key].arn}:*" },
    { Effect = "Allow", Action = ["secretsmanager:GetSecretValue"], Resource = local.secret_access[each.key] },
    { Effect    = "Allow", Action = ["kms:Decrypt"], Resource = aws_kms_key.main.arn,
      Condition = { StringEquals = { "kms:ViaService" = "secretsmanager.${var.region}.amazonaws.com" }, StringLike = { "kms:EncryptionContext:SecretARN" = local.secret_access[each.key] } }
    }
  ] })
}
resource "aws_iam_role" "task" {
  for_each           = local.roles
  name               = "${var.name}-${each.key}-task"
  assume_role_policy = local.task_trust
}
resource "aws_iam_role_policy" "bedrock" {
  name = "invoke-selected-model"
  role = aws_iam_role.task["worker"].id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = ["bedrock:InvokeModel"], Resource = var.bedrock_resource_arns,
    Condition = { StringEquals = { "aws:SourceVpce" = aws_vpc_endpoint.bedrock.id } }
  }] })
}
