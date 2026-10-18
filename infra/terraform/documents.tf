locals {
  document_prefix = "originals/"
  document_arn    = "${aws_s3_bucket.originals.arn}/${local.document_prefix}*"
  validation_arn  = "${aws_s3_bucket.originals.arn}/malware-protection-resource-validation-object"
  document_access = {
    app    = ["s3:PutObject", "s3:GetObject", "s3:GetObjectTagging"]
    worker = ["s3:GetObject", "s3:GetObjectTagging"]
    relay  = ["s3:DeleteObject"]
  }
}
resource "aws_s3_bucket" "originals" {
  bucket        = "${var.name}-originals-${var.account_id}-${var.region}"
  force_destroy = false
  lifecycle {
    prevent_destroy = true
  }
}
resource "aws_s3_bucket_public_access_block" "originals" {
  bucket                  = aws_s3_bucket.originals.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_ownership_controls" "originals" {
  bucket = aws_s3_bucket.originals.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}
resource "aws_s3_bucket_versioning" "originals" {
  bucket = aws_s3_bucket.originals.id
  versioning_configuration {
    status = "Suspended"
  }
}
resource "aws_s3_bucket_server_side_encryption_configuration" "originals" {
  bucket = aws_s3_bucket.originals.id
  rule {
    bucket_key_enabled = false
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.main.arn
    }
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "originals" {
  bucket = aws_s3_bucket.originals.id
  rule {
    id     = "original-retention-backstop"
    status = "Enabled"
    filter {
      prefix = local.document_prefix
    }
    expiration {
      days = var.document_retention_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
  rule {
    id     = "scan-validation-cleanup"
    status = "Enabled"
    filter {
      prefix = "malware-protection-resource-validation-object"
    }
    expiration {
      days = 1
    }
  }
}
resource "aws_s3_bucket_notification" "originals" {
  bucket      = aws_s3_bucket.originals.id
  eventbridge = true
}
resource "aws_iam_role" "document_scan" {
  name = "${var.name}-document-scan"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect = "Allow", Principal = { Service = "malware-protection-plan.guardduty.amazonaws.com" }, Action = "sts:AssumeRole"
  }] })
}
resource "aws_iam_role_policy" "document_scan" {
  name = "scan-originals"
  role = aws_iam_role.document_scan.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Sid       = "ManageGuardDutyRule", Effect = "Allow", Action = ["events:PutRule", "events:DeleteRule", "events:PutTargets", "events:RemoveTargets"],
      Resource  = "arn:aws:events:${var.region}:${var.account_id}:rule/DO-NOT-DELETE-AmazonGuardDutyMalwareProtectionS3*",
      Condition = { StringEquals = { "events:ManagedBy" = "malware-protection-plan.guardduty.amazonaws.com" } }
    },
    { Sid      = "ReadGuardDutyRule", Effect = "Allow", Action = ["events:DescribeRule", "events:ListTargetsByRule"],
      Resource = "arn:aws:events:${var.region}:${var.account_id}:rule/DO-NOT-DELETE-AmazonGuardDutyMalwareProtectionS3*"
    },
    { Sid = "BucketIntegration", Effect = "Allow", Action = ["s3:GetBucketNotification", "s3:PutBucketNotification", "s3:ListBucket"], Resource = aws_s3_bucket.originals.arn },
    { Sid = "ValidateBucket", Effect = "Allow", Action = ["s3:PutObject"], Resource = local.validation_arn },
    { Sid = "ReadAndTagOriginals", Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion", "s3:GetObjectTagging", "s3:GetObjectVersionTagging", "s3:PutObjectTagging", "s3:PutObjectVersionTagging"], Resource = local.document_arn },
    { Sid       = "DecryptScanAndEncryptValidation", Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Decrypt"], Resource = aws_kms_key.main.arn,
      Condition = { StringEquals = { "kms:ViaService" = "s3.${var.region}.amazonaws.com" }, ArnLike = { "kms:EncryptionContext:aws:s3:arn" = [local.document_arn, local.validation_arn] } }
    }
  ] })
}
resource "aws_s3_bucket_policy" "originals" {
  bucket = aws_s3_bucket.originals.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Sid = "RequireTLS", Effect = "Deny", Principal = "*", Action = "s3:*", Resource = [aws_s3_bucket.originals.arn, "${aws_s3_bucket.originals.arn}/*"], Condition = { Bool = { "aws:SecureTransport" = "false" } } },
    { Sid       = "NoReadUnlessClean", Effect = "Deny", Principal = "*", Action = ["s3:GetObject", "s3:GetObjectVersion"], Resource = local.document_arn,
      Condition = { StringNotEquals = { "s3:ExistingObjectTag/GuardDutyMalwareScanStatus" = "NO_THREATS_FOUND" }, ArnNotEquals = { "aws:PrincipalArn" = aws_iam_role.document_scan.arn } }
    },
    { Sid       = "OnlyScannerCanChangeTags", Effect = "Deny", Principal = "*", Action = ["s3:PutObjectTagging", "s3:PutObjectVersionTagging", "s3:DeleteObjectTagging", "s3:DeleteObjectVersionTagging"], Resource = local.document_arn,
      Condition = { ArnNotEquals = { "aws:PrincipalArn" = aws_iam_role.document_scan.arn } }
    },
    { Sid       = "NeverUploadScanResult", Effect = "Deny", Principal = "*", Action = "s3:PutObject", Resource = local.document_arn,
      Condition = { "ForAnyValue:StringEquals" = { "s3:RequestObjectTagKeys" = "GuardDutyMalwareScanStatus" } }
    },
    { Sid       = "RejectEncryptionOverride", Effect = "Deny", Principal = "*", Action = "s3:PutObject", Resource = "${aws_s3_bucket.originals.arn}/*",
      Condition = { Null = { "s3:x-amz-server-side-encryption" = "false" }, StringNotEquals = { "s3:x-amz-server-side-encryption" = "aws:kms" } }
    },
    { Sid       = "RejectKMSKeyOverride", Effect = "Deny", Principal = "*", Action = "s3:PutObject", Resource = "${aws_s3_bucket.originals.arn}/*",
      Condition = { Null = { "s3:x-amz-server-side-encryption-aws-kms-key-id" = "false" }, StringNotEquals = { "s3:x-amz-server-side-encryption-aws-kms-key-id" = aws_kms_key.main.arn } }
    },
    { Sid       = "RejectImplicitManagedKMSKey", Effect = "Deny", Principal = "*", Action = "s3:PutObject", Resource = "${aws_s3_bucket.originals.arn}/*",
      Condition = { Null = { "s3:x-amz-server-side-encryption-aws-kms-key-id" = "true" }, StringEquals = { "s3:x-amz-server-side-encryption" = "aws:kms" } }
    }
  ] })
  depends_on = [aws_s3_bucket_public_access_block.originals]
}
resource "aws_guardduty_malware_protection_plan" "originals" {
  role = aws_iam_role.document_scan.arn
  protected_resource {
    s3_bucket {
      bucket_name     = aws_s3_bucket.originals.id
      object_prefixes = [local.document_prefix]
    }
  }
  actions {
    tagging {
      status = "ENABLED"
    }
  }
  depends_on = [aws_iam_role_policy.document_scan, aws_s3_bucket_policy.originals, aws_s3_bucket_notification.originals, aws_s3_bucket_server_side_encryption_configuration.originals]
}
resource "aws_iam_role_policy" "documents" {
  for_each = local.document_access
  name     = "document-objects"
  role     = aws_iam_role.task[each.key].id
  policy = jsonencode({ Version = "2012-10-17", Statement = concat([
    { Sid       = "OriginalObjects", Effect = "Allow", Action = each.value, Resource = local.document_arn,
      Condition = { StringEquals = { "aws:SourceVpce" = aws_vpc_endpoint.s3_layers.id } }
    }
    ], each.key == "relay" ? [] : [
    { Sid       = "OriginalEncryption", Effect = "Allow", Action = each.key == "app" ? ["kms:GenerateDataKey", "kms:Decrypt"] : ["kms:Decrypt"], Resource = aws_kms_key.main.arn,
      Condition = { StringEquals = { "kms:ViaService" = "s3.${var.region}.amazonaws.com" }, ArnLike = { "kms:EncryptionContext:aws:s3:arn" = local.document_arn } }
    }
  ]) })
}
