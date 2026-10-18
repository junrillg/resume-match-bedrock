output "application_url" {
  value = "https://${var.hostname}"
}
output "repositories" {
  value = { for name, repo in aws_ecr_repository.image : name => repo.repository_url }
}
output "cluster_name" {
  value = aws_ecs_cluster.main.name
}
output "bootstrap_task_definition" {
  value = try(aws_ecs_task_definition.service["bootstrap"].arn, null)
}
output "bootstrap_network" {
  value = {
    awsvpcConfiguration = {
      subnets        = [for subnet in aws_subnet.private : subnet.id]
      securityGroups = [aws_security_group.task["bootstrap"].id]
      assignPublicIp = "DISABLED"
    }
  }
}
output "service_names" {
  value = { for role, service in aws_ecs_service.main : role => service.name }
}
output "reviewer_secret_arn" {
  description = "Identifier only. Authorized operators retrieve the initial password privately in Secrets Manager."
  value       = aws_secretsmanager_secret.app["reviewer"].arn
}
output "log_groups" {
  value = { for role, group in aws_cloudwatch_log_group.service : role => group.name }
}

output "document_bucket" {
  value = aws_s3_bucket.originals.id
}
output "document_scan_plan" {
  value = { arn = aws_guardduty_malware_protection_plan.originals.arn, status = aws_guardduty_malware_protection_plan.originals.status }
}
