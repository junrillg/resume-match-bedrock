mock_provider "aws" {
  override_during = plan
  mock_resource "aws_vpc" {
    defaults = { id = "vpc-0123456789abcdef0" }
  }
  mock_resource "aws_subnet" {
    defaults = { id = "subnet-0123456789abcdef0" }
  }
  mock_resource "aws_route_table" {
    defaults = { route = [] }
  }
  mock_resource "aws_security_group" {
    defaults = { id = "sg-0123456789abcdef0" }
  }
  mock_resource "aws_vpc_endpoint" {
    defaults = { id = "vpce-0123456789abcdef0", prefix_list_id = "pl-01234567" }
  }
  mock_resource "aws_kms_key" {
    defaults = { arn = "arn:aws:kms:us-east-1:111122223333:key/12345678-1234-1234-1234-123456789012", key_id = "12345678-1234-1234-1234-123456789012" }
  }
  mock_resource "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::111122223333:role/mock-role" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { id = "resume-match-originals-111122223333-us-east-1", arn = "arn:aws:s3:::resume-match-originals-111122223333-us-east-1" }
  }
  mock_resource "aws_guardduty_malware_protection_plan" {
    defaults = { arn = "arn:aws:guardduty:us-east-1:111122223333:malware-protection-plan/1234567890abcdef", status = "ACTIVE" }
  }
  mock_resource "aws_db_instance" {
    defaults = { address = "db.example.invalid", master_user_secret = [{ secret_arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:master-AbCdEf", secret_status = "active", kms_key_id = "12345678-1234-1234-1234-123456789012" }] }
  }
  mock_resource "aws_mq_broker" {
    defaults = { instances = [{ console_url = "https://broker.example.invalid", endpoints = ["amqps://broker.example.invalid:5671"], ip_address = "10.42.10.20" }] }
  }
  mock_resource "aws_acm_certificate" {
    defaults = { arn = "arn:aws:acm:us-east-1:111122223333:certificate/12345678-1234-1234-1234-123456789012", domain_validation_options = [{ domain_name = "resume.example.com", resource_record_name = "_validation.resume.example.com", resource_record_type = "CNAME", resource_record_value = "_validation.acm-validations.aws" }] }
  }
  mock_resource "aws_acm_certificate_validation" {
    defaults = { certificate_arn = "arn:aws:acm:us-east-1:111122223333:certificate/12345678-1234-1234-1234-123456789012" }
  }
  mock_resource "aws_lb" {
    defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:111122223333:loadbalancer/app/resume-match/1234567890123456" }
  }
  mock_resource "aws_lb_target_group" {
    defaults = { arn = "arn:aws:elasticloadbalancing:us-east-1:111122223333:targetgroup/resume-match/1234567890123456" }
  }
  mock_resource "aws_ecr_repository" {
    defaults = { arn = "arn:aws:ecr:us-east-1:111122223333:repository/resume-match/api", repository_url = "111122223333.dkr.ecr.us-east-1.amazonaws.com/resume-match/api" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:us-east-1:111122223333:log-group:/ecs/resume-match/mock" }
  }
  mock_resource "aws_secretsmanager_secret" {
    defaults = { arn = "arn:aws:secretsmanager:us-east-1:111122223333:secret:app-AbCdEf" }
  }
  mock_resource "aws_ecs_task_definition" {
    defaults = { arn = "arn:aws:ecs:us-east-1:111122223333:task-definition/resume-match:1" }
  }
}
mock_provider "random" {
  override_during = plan
  mock_resource "random_password" {
    defaults = { result = "synthetic-test-password-not-a-real-credential-123456789" }
  }
}
override_resource {
  target          = aws_subnet.private["us-east-1a"]
  override_during = plan
  values          = { id = "subnet-00000000000000001" }
}
override_resource {
  target          = aws_subnet.private["us-east-1b"]
  override_during = plan
  values          = { id = "subnet-00000000000000002" }
}
override_resource {
  target          = aws_subnet.private["us-east-1c"]
  override_during = plan
  values          = { id = "subnet-00000000000000003" }
}
override_resource {
  target          = aws_iam_role.task["app"]
  override_during = plan
  values          = { id = "resume-match-app-task", arn = "arn:aws:iam::111122223333:role/resume-match-app-task" }
}
override_resource {
  target          = aws_iam_role.task["relay"]
  override_during = plan
  values          = { id = "resume-match-relay-task", arn = "arn:aws:iam::111122223333:role/resume-match-relay-task" }
}
override_resource {
  target          = aws_iam_role.task["worker"]
  override_during = plan
  values          = { id = "resume-match-worker-task", arn = "arn:aws:iam::111122223333:role/resume-match-worker-task" }
}
override_resource {
  target          = aws_iam_role.task["bootstrap"]
  override_during = plan
  values          = { id = "resume-match-bootstrap-task", arn = "arn:aws:iam::111122223333:role/resume-match-bootstrap-task" }
}
override_resource {
  target          = aws_iam_role.document_scan
  override_during = plan
  values          = { id = "resume-match-document-scan", arn = "arn:aws:iam::111122223333:role/resume-match-document-scan" }
}
variables {
  account_id              = "111122223333"
  region                  = "us-east-1"
  availability_zones      = ["us-east-1a", "us-east-1b", "us-east-1c"]
  public_zone_id          = "Z0123456789EXAMPLE"
  hostname                = "resume.example.com"
  postgres_engine_version = "17.11"
  bedrock_model_id        = "example.model-v1:0"
  bedrock_resource_arns   = ["arn:aws:bedrock:us-east-1::foundation-model/example.model-v1:0"]
}
run "foundation_without_images" {
  command = plan
  assert {
    condition     = length(aws_ecs_task_definition.service) == 0 && length(aws_ecs_service.main) == 0
    error_message = "Foundation must not start tasks or reference placeholder image digests."
  }
  assert {
    condition     = length(aws_subnet.private) == 3 && length(aws_route_table.private.route) == 0 && aws_vpc_endpoint.s3_layers.vpc_endpoint_type == "Gateway" && length(aws_vpc_endpoint.service) == 4
    error_message = "Private tasks need three AZs, no default internet route, four startup endpoints and ECR layer access."
  }
  assert {
    condition     = aws_db_instance.main.multi_az && !aws_db_instance.main.publicly_accessible && aws_db_instance.main.manage_master_user_password && aws_db_instance.main.storage_encrypted && aws_db_instance.main.backup_retention_period >= 7 && !aws_db_instance.main.skip_final_snapshot
    error_message = "Database must be private, encrypted, managed-master and recoverable."
  }
  assert {
    condition     = aws_mq_broker.main.deployment_mode == "CLUSTER_MULTI_AZ" && aws_mq_broker.main.engine_version == "4.3" && !aws_mq_broker.main.publicly_accessible && length(aws_mq_broker.main.subnet_ids) == 3
    error_message = "RabbitMQ quorum topology requires the selected private three-AZ cluster."
  }
  assert {
    condition     = aws_lb_listener.https.protocol == "HTTPS" && aws_lb_listener.https.port == 443 && aws_lb_target_group.app.port == 8080 && aws_lb_target_group.app.health_check[0].path == "/api/health/"
    error_message = "Ingress must terminate HTTPS and expose only nginx plus DB-aware readiness."
  }
  assert {
    condition     = alltrue([for group in aws_cloudwatch_log_group.service : group.retention_in_days == 30 && group.kms_key_id == aws_kms_key.main.arn && group.skip_destroy]) && aws_kms_key.main.enable_key_rotation
    error_message = "Application logs require bounded retention, KMS encryption and retention on destroy."
  }
  assert {
    condition     = !strcontains(aws_iam_role_policy.execution["app"].policy, aws_db_instance.main.master_user_secret[0].secret_arn) && strcontains(aws_iam_role_policy.execution["bootstrap"].policy, aws_db_instance.main.master_user_secret[0].secret_arn)
    error_message = "Only bootstrap execution may read the managed master secret."
  }
  assert {
    condition     = toset(jsondecode(aws_iam_role_policy.bedrock.policy).Statement[0].Resource) == var.bedrock_resource_arns && jsondecode(aws_iam_role_policy.bedrock.policy).Statement[0].Condition.StringEquals["aws:SourceVpce"] == aws_vpc_endpoint.bedrock.id
    error_message = "Worker model invocation must name exact resources and the private endpoint."
  }
}
run "staged_tasks_before_bootstrap" {
  command = plan
  variables {
    image_digests = { api = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", web = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
  }
  assert {
    condition     = length(aws_ecs_task_definition.service) == 4 && alltrue([for service in aws_ecs_service.main : service.desired_count == 0 && !service.network_configuration[0].assign_public_ip])
    error_message = "Image publication defines tasks but must leave normal services stopped before bootstrap."
  }
  assert {
    condition     = length(jsondecode(aws_ecs_task_definition.service["app"].container_definitions)) == 2 && jsondecode(aws_ecs_task_definition.service["app"].container_definitions)[0].command[3] == "127.0.0.1:8000" && jsondecode(aws_ecs_task_definition.service["app"].container_definitions)[1].portMappings[0].containerPort == 8080
    error_message = "The app task must colocate nginx and a localhost-only Django server."
  }
  assert {
    condition     = local.environment.POSTGRES_SSLMODE == "verify-full" && local.environment.RABBITMQ_TLS == "true" && local.environment.MATCH_PROVIDER == "bedrock" && local.environment.RABBITMQ_HOST == "broker.example.invalid" && !contains(keys(local.environment), "BEDROCK_LOCAL_ENDPOINT")
    error_message = "Cloud tasks need verified RDS/MQ TLS and the real Bedrock SDK route."
  }
  assert {
    condition     = join(" ", jsondecode(aws_ecs_task_definition.service["bootstrap"].container_definitions)[0].command) == "python manage.py bootstrap_cloud_db" && !contains([for secret in jsondecode(aws_ecs_task_definition.service["worker"].container_definitions)[0].secrets : secret.name], "RDS_MASTER_PASSWORD")
    error_message = "Master credentials belong only to the one-off bootstrap task."
  }
}
run "reject_early_enable" {
  command = plan
  variables {
    enable_services = true
  }
  expect_failures = [var.enable_services]
}
run "reject_missing_bootstrap_confirmation" {
  command = plan
  variables {
    image_digests   = { api = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", web = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
    enable_services = true
  }
  expect_failures = [var.bootstrap_completed]
}
run "enabled_after_bootstrap" {
  command = plan
  variables {
    image_digests       = { api = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", web = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
    enable_services     = true
    bootstrap_completed = true
  }
  assert {
    condition     = aws_ecs_service.main["app"].desired_count == 2 && aws_ecs_service.main["worker"].desired_count == 2 && aws_ecs_service.main["relay"].desired_count == 1
    error_message = "Only explicit post-bootstrap enablement may start the selected replicas."
  }
}

run "durable_documents" {
  command = plan
  assert {
    condition = (
      !aws_s3_bucket.originals.force_destroy &&
      aws_s3_bucket_public_access_block.originals.block_public_acls &&
      aws_s3_bucket_public_access_block.originals.block_public_policy &&
      aws_s3_bucket_public_access_block.originals.ignore_public_acls &&
      aws_s3_bucket_public_access_block.originals.restrict_public_buckets &&
      aws_s3_bucket_ownership_controls.originals.rule[0].object_ownership == "BucketOwnerEnforced" &&
      aws_s3_bucket_versioning.originals.versioning_configuration[0].status == "Suspended"
    )
    error_message = "Originals must have private owner-controlled access without retained historical versions or automatic destructive cleanup."
  }
  assert {
    condition = alltrue([for rule in aws_s3_bucket_server_side_encryption_configuration.originals.rule :
      !rule.bucket_key_enabled && rule.apply_server_side_encryption_by_default[0].sse_algorithm == "aws:kms" && rule.apply_server_side_encryption_by_default[0].kms_master_key_id == aws_kms_key.main.arn
    ])
    error_message = "Default encryption must use the selected KMS key and object-level encryption context."
  }
  assert {
    condition = (
      one([for rule in aws_s3_bucket_lifecycle_configuration.originals.rule : rule if rule.id == "original-retention-backstop"]).expiration[0].days == var.document_retention_days &&
      one([for rule in aws_s3_bucket_lifecycle_configuration.originals.rule : rule if rule.id == "original-retention-backstop"]).filter[0].prefix == "originals/" &&
      local.environment.DOCUMENT_RETENTION_DAYS == tostring(var.document_retention_days)
    )
    error_message = "S3 expiry backstop and application policy must agree, scoped to generated original keys."
  }
  assert {
    condition = (
      aws_guardduty_malware_protection_plan.originals.role == aws_iam_role.document_scan.arn &&
      aws_guardduty_malware_protection_plan.originals.protected_resource[0].s3_bucket[0].bucket_name == aws_s3_bucket.originals.id &&
      toset(aws_guardduty_malware_protection_plan.originals.protected_resource[0].s3_bucket[0].object_prefixes) == toset(["originals/"]) &&
      aws_guardduty_malware_protection_plan.originals.actions[0].tagging[0].status == "ENABLED" &&
      aws_s3_bucket_notification.originals.eventbridge
    )
    error_message = "New originals must reach the scanner with scan-result tagging enabled through EventBridge."
  }
  assert {
    condition = (
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "NoReadUnlessClean"]).Effect == "Deny" &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "NoReadUnlessClean"]).Condition.StringNotEquals["s3:ExistingObjectTag/GuardDutyMalwareScanStatus"] == "NO_THREATS_FOUND" &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "NoReadUnlessClean"]).Condition.ArnNotEquals["aws:PrincipalArn"] == aws_iam_role.document_scan.arn &&
      toset(one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "NoReadUnlessClean"]).Action) == toset(["s3:GetObject", "s3:GetObjectVersion"])
    )
    error_message = "Only the scanner can read an untagged, pending or non-clean original; app and worker cannot bypass the gate."
  }
  assert {
    condition = (
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "NeverUploadScanResult"]).Effect == "Deny" &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "NeverUploadScanResult"]).Action == "s3:PutObject" &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "NeverUploadScanResult"]).Condition["ForAnyValue:StringEquals"]["s3:RequestObjectTagKeys"] == "GuardDutyMalwareScanStatus" &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "OnlyScannerCanChangeTags"]).Effect == "Deny" &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "OnlyScannerCanChangeTags"]).Condition.ArnNotEquals["aws:PrincipalArn"] == aws_iam_role.document_scan.arn &&
      toset(one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "OnlyScannerCanChangeTags"]).Action) == toset(["s3:PutObjectTagging", "s3:PutObjectVersionTagging", "s3:DeleteObjectTagging", "s3:DeleteObjectVersionTagging"])
    )
    error_message = "Applications cannot forge scan results during PUT or replace/delete scanner tags."
  }
  assert {
    condition = (
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "RejectKMSKeyOverride"]).Condition.StringNotEquals["s3:x-amz-server-side-encryption-aws-kms-key-id"] == aws_kms_key.main.arn &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "RejectEncryptionOverride"]).Condition.StringNotEquals["s3:x-amz-server-side-encryption"] == "aws:kms" &&
      one([for statement in jsondecode(aws_s3_bucket_policy.originals.policy).Statement : statement if statement.Sid == "RejectImplicitManagedKMSKey"]).Condition.Null["s3:x-amz-server-side-encryption-aws-kms-key-id"] == "true"
    )
    error_message = "Default encryption must not be bypassed with another key or encryption algorithm."
  }
  assert {
    condition = (
      toset(keys(aws_iam_role_policy.documents)) == toset(["app", "worker", "relay"]) &&
      toset(jsondecode(aws_iam_role_policy.documents["app"].policy).Statement[0].Action) == toset(["s3:PutObject", "s3:GetObject", "s3:GetObjectTagging"]) &&
      toset(jsondecode(aws_iam_role_policy.documents["worker"].policy).Statement[0].Action) == toset(["s3:GetObject", "s3:GetObjectTagging"]) &&
      toset(jsondecode(aws_iam_role_policy.documents["relay"].policy).Statement[0].Action) == toset(["s3:DeleteObject"]) &&
      length(jsondecode(aws_iam_role_policy.documents["relay"].policy).Statement) == 1 &&
      alltrue([for policy in aws_iam_role_policy.documents : jsondecode(policy.policy).Statement[0].Resource == "${aws_s3_bucket.originals.arn}/originals/*" && jsondecode(policy.policy).Statement[0].Condition.StringEquals["aws:SourceVpce"] == aws_vpc_endpoint.s3_layers.id])
    )
    error_message = "Only API may upload, worker may read, relay may delete, and bootstrap has no document access; all application objects use generated original keys through the endpoint."
  }
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.documents["app"].policy).Statement[1].Condition.ArnLike["kms:EncryptionContext:aws:s3:arn"] == "${aws_s3_bucket.originals.arn}/originals/*" &&
      jsondecode(aws_iam_role_policy.documents["app"].policy).Statement[1].Condition.StringEquals["kms:ViaService"] == "s3.${var.region}.amazonaws.com" &&
      toset(jsondecode(aws_iam_role_policy.documents["app"].policy).Statement[1].Action) == toset(["kms:GenerateDataKey", "kms:Decrypt"]) &&
      toset(jsondecode(aws_iam_role_policy.documents["worker"].policy).Statement[1].Action) == toset(["kms:Decrypt"])
    )
    error_message = "Document KMS permissions must be limited to S3 original-object context and each role's actual operation."
  }
  assert {
    condition = (
      toset(one([for statement in jsondecode(aws_vpc_endpoint.s3_layers.policy).Statement : statement if statement.Sid == "ECRImageLayers"]).Resource) == toset(["arn:aws:s3:::prod-${var.region}-starport-layer-bucket/*"]) &&
      toset(one([for statement in jsondecode(aws_vpc_endpoint.s3_layers.policy).Statement : statement if statement.Sid == "ECRImageLayers"]).Action) == toset(["s3:GetObject"]) &&
      length(jsondecode(aws_vpc_endpoint.s3_layers.policy).Statement) == 4 &&
      alltrue([for role, actions in local.document_access :
        one([for statement in jsondecode(aws_vpc_endpoint.s3_layers.policy).Statement : statement if statement.Sid == "Document${title(role)}"]).Principal.AWS == aws_iam_role.task[role].arn &&
        toset(one([for statement in jsondecode(aws_vpc_endpoint.s3_layers.policy).Statement : statement if statement.Sid == "Document${title(role)}"]).Resource) == toset(["${aws_s3_bucket.originals.arn}/originals/*"])
      ])
    )
    error_message = "The S3 endpoint must preserve ECR layer access while restricting documents to their three separate task roles."
  }
  assert {
    condition = (
      local.environment.DOCUMENT_BUCKET == aws_s3_bucket.originals.id && local.environment.DOCUMENT_REGION == var.region && local.environment.DOCUMENT_SCAN_MODE == "guardduty" &&
      alltrue([for name in ["DOCUMENT_ENDPOINT", "DOCUMENT_ACCESS_KEY", "DOCUMENT_SECRET_KEY"] : !contains(keys(local.environment), name)])
    )
    error_message = "Cloud tasks must use the real bucket/region/GuardDuty with task credentials, never local endpoints or keys."
  }
  assert {
    condition = (
      one([for statement in jsondecode(aws_iam_role_policy.document_scan.policy).Statement : statement if statement.Sid == "ValidateBucket"]).Resource == "${aws_s3_bucket.originals.arn}/malware-protection-resource-validation-object" &&
      one([for statement in jsondecode(aws_iam_role_policy.document_scan.policy).Statement : statement if statement.Sid == "ReadAndTagOriginals"]).Resource == "${aws_s3_bucket.originals.arn}/originals/*" &&
      one([for statement in jsondecode(aws_iam_role_policy.document_scan.policy).Statement : statement if statement.Sid == "ManageGuardDutyRule"]).Condition.StringEquals["events:ManagedBy"] == "malware-protection-plan.guardduty.amazonaws.com" &&
      toset(one([for statement in jsondecode(aws_iam_role_policy.document_scan.policy).Statement : statement if statement.Sid == "DecryptScanAndEncryptValidation"]).Condition.ArnLike["kms:EncryptionContext:aws:s3:arn"]) == toset(["${aws_s3_bucket.originals.arn}/originals/*", "${aws_s3_bucket.originals.arn}/malware-protection-resource-validation-object"])
    )
    error_message = "Scanner setup must include the precise validation object, EventBridge ownership condition and required encrypted-object contexts."
  }
}
run "reject_invalid_document_retention" {
  command = plan
  variables {
    document_retention_days = 0
  }
  expect_failures = [var.document_retention_days]
}
run "block_enable_when_scan_protection_is_not_active" {
  command = plan
  variables {
    image_digests       = { api = "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", web = "sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" }
    enable_services     = true
    bootstrap_completed = true
  }
  override_resource {
    target          = aws_guardduty_malware_protection_plan.originals
    override_during = plan
    values          = { status = "WARNING" }
  }
  expect_failures = [aws_ecs_service.main]
}
