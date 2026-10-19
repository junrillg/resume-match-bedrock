resource "aws_acm_certificate" "main" {
  domain_name       = var.hostname
  validation_method = "DNS"
  lifecycle {
    create_before_destroy = true
  }
}
resource "aws_route53_record" "validation" {
  for_each = { for option in aws_acm_certificate.main.domain_validation_options : option.domain_name => option }
  zone_id  = var.public_zone_id
  name     = each.value.resource_record_name
  type     = each.value.resource_record_type
  ttl      = 60
  records  = [each.value.resource_record_value]
}
resource "aws_acm_certificate_validation" "main" {
  certificate_arn         = aws_acm_certificate.main.arn
  validation_record_fqdns = [for record in aws_route53_record.validation : record.fqdn]
}
resource "aws_lb" "main" {
  name                       = var.name
  internal                   = false
  load_balancer_type         = "application"
  subnets                    = [for subnet in aws_subnet.public : subnet.id]
  security_groups            = [aws_security_group.alb.id]
  enable_deletion_protection = var.deletion_protection
  drop_invalid_header_fields = true
  idle_timeout               = 60
}
resource "aws_lb_target_group" "app" {
  name                 = var.name
  port                 = 8080
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = aws_vpc.main.id
  deregistration_delay = 30
  health_check {
    path                = "/api/health/"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}
resource "aws_lb_listener" "https" {
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = aws_acm_certificate_validation.main.certificate_arn
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app.arn
  }
}
resource "aws_route53_record" "app" {
  zone_id = var.public_zone_id
  name    = var.hostname
  type    = "A"
  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}

resource "aws_lb_target_group" "gateway" {
  name                          = "${var.name}-events"
  port                          = 8001
  protocol                      = "HTTP"
  target_type                   = "ip"
  vpc_id                        = aws_vpc.main.id
  deregistration_delay          = 30
  load_balancing_algorithm_type = "least_outstanding_requests"
  health_check {
    path                = "/health/"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}
resource "aws_lb_listener_rule" "events" {
  listener_arn = aws_lb_listener.https.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.gateway.arn
  }
  condition {
    path_pattern { values = ["/api/events/"] }
  }
}
resource "aws_vpc_security_group_ingress_rule" "gateway" {
  security_group_id            = aws_security_group.task["gateway"].id
  referenced_security_group_id = aws_security_group.alb.id
  ip_protocol                  = "tcp"
  from_port                    = 8001
  to_port                      = 8001
}
resource "aws_vpc_security_group_egress_rule" "alb_gateway" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.task["gateway"].id
  ip_protocol                  = "tcp"
  from_port                    = 8001
  to_port                      = 8001
}
