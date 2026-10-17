locals {
  zones = { for index, az in var.availability_zones : az => index }
  roles = toset(["app", "relay", "worker", "bootstrap"])
}
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
}
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}
resource "aws_subnet" "public" {
  for_each          = local.zones
  vpc_id            = aws_vpc.main.id
  availability_zone = each.key
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, each.value)
}
resource "aws_subnet" "private" {
  for_each          = local.zones
  vpc_id            = aws_vpc.main.id
  availability_zone = each.key
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, each.value + 10)
}
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
}
resource "aws_route_table_association" "public" {
  for_each       = local.zones
  subnet_id      = aws_subnet.public[each.key].id
  route_table_id = aws_route_table.public.id
}
resource "aws_route_table_association" "private" {
  for_each       = local.zones
  subnet_id      = aws_subnet.private[each.key].id
  route_table_id = aws_route_table.private.id
}
resource "aws_security_group" "alb" {
  name_prefix = "${var.name}-alb-"
  vpc_id      = aws_vpc.main.id
}
resource "aws_security_group" "task" {
  for_each    = local.roles
  name_prefix = "${var.name}-${each.key}-"
  vpc_id      = aws_vpc.main.id
}
resource "aws_security_group" "database" {
  name_prefix = "${var.name}-db-"
  vpc_id      = aws_vpc.main.id
}
resource "aws_security_group" "broker" {
  name_prefix = "${var.name}-mq-"
  vpc_id      = aws_vpc.main.id
}
resource "aws_security_group" "endpoints" {
  name_prefix = "${var.name}-endpoints-"
  vpc_id      = aws_vpc.main.id
}
resource "aws_security_group" "bedrock" {
  name_prefix = "${var.name}-bedrock-"
  vpc_id      = aws_vpc.main.id
}
resource "aws_vpc_security_group_ingress_rule" "https" {
  security_group_id = aws_security_group.alb.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
resource "aws_vpc_security_group_ingress_rule" "web" {
  security_group_id            = aws_security_group.task["app"].id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}
resource "aws_vpc_security_group_egress_rule" "alb_web" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.task["app"].id
  ip_protocol                  = "tcp"
  from_port                    = 8080
  to_port                      = 8080
}
resource "aws_vpc_security_group_ingress_rule" "database" {
  for_each                     = local.roles
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.task[each.key].id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_egress_rule" "database" {
  for_each                     = local.roles
  security_group_id            = aws_security_group.task[each.key].id
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}
resource "aws_vpc_security_group_ingress_rule" "broker" {
  for_each                     = toset(["relay", "worker"])
  security_group_id            = aws_security_group.broker.id
  referenced_security_group_id = aws_security_group.task[each.key].id
  ip_protocol                  = "tcp"
  from_port                    = 5671
  to_port                      = 5671
}
resource "aws_vpc_security_group_egress_rule" "broker" {
  for_each                     = toset(["relay", "worker"])
  security_group_id            = aws_security_group.task[each.key].id
  referenced_security_group_id = aws_security_group.broker.id
  ip_protocol                  = "tcp"
  from_port                    = 5671
  to_port                      = 5671
}
resource "aws_vpc_security_group_ingress_rule" "broker_cluster" {
  security_group_id            = aws_security_group.broker.id
  referenced_security_group_id = aws_security_group.broker.id
  ip_protocol                  = "-1"
}
resource "aws_vpc_security_group_egress_rule" "broker_cluster" {
  security_group_id            = aws_security_group.broker.id
  referenced_security_group_id = aws_security_group.broker.id
  ip_protocol                  = "-1"
}
resource "aws_vpc_security_group_ingress_rule" "endpoints" {
  for_each                     = local.roles
  security_group_id            = aws_security_group.endpoints.id
  referenced_security_group_id = aws_security_group.task[each.key].id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
resource "aws_vpc_security_group_egress_rule" "endpoints" {
  for_each                     = local.roles
  security_group_id            = aws_security_group.task[each.key].id
  referenced_security_group_id = aws_security_group.endpoints.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
resource "aws_vpc_security_group_ingress_rule" "bedrock" {
  security_group_id            = aws_security_group.bedrock.id
  referenced_security_group_id = aws_security_group.task["worker"].id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
resource "aws_vpc_security_group_egress_rule" "bedrock" {
  security_group_id            = aws_security_group.task["worker"].id
  referenced_security_group_id = aws_security_group.bedrock.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
resource "aws_vpc_endpoint" "service" {
  for_each            = toset(["ecr.api", "ecr.dkr", "logs", "secretsmanager"])
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [for subnet in aws_subnet.private : subnet.id]
  security_group_ids  = [aws_security_group.endpoints.id]
}
resource "aws_vpc_endpoint" "bedrock" {
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = [for subnet in aws_subnet.private : subnet.id]
  security_group_ids  = [aws_security_group.bedrock.id]
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { AWS = aws_iam_role.task["worker"].arn },
    Action = ["bedrock:InvokeModel"], Resource = var.bedrock_resource_arns
  }] })
}
resource "aws_vpc_endpoint" "s3_layers" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow", Principal = "*", Action = ["s3:GetObject"],
    Resource = ["arn:aws:s3:::prod-${var.region}-starport-layer-bucket/*"]
  }] })
}
resource "aws_vpc_security_group_egress_rule" "s3_layers" {
  for_each          = local.roles
  security_group_id = aws_security_group.task[each.key].id
  prefix_list_id    = aws_vpc_endpoint.s3_layers.prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
