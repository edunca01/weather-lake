# Compute layer: the image registry, the poller and compaction Lambdas (one image, the handler
# chosen by the image command) with their least-privilege roles, one schedule per product read
# from config.yaml, and hourly compaction.

# -- Image registry -------------------------------------------------------------------------

resource "aws_ecr_repository" "ingest" {
  name                 = var.image_repository
  image_tag_mutability = "MUTABLE" # tags may move; the Lambda pins a digest, not a tag

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "ingest" {
  repository = aws_ecr_repository.ingest.name

  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "keep the last 10 images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# Resolved at plan time, so a plan always shows when the running code would change. It fails
# until an image with this tag exists: the first deploy creates the repository alone, pushes,
# then plans the rest.
data "aws_ecr_image" "ingest" {
  repository_name = aws_ecr_repository.ingest.name
  image_tag       = var.image_tag
}

locals {
  image_uri = "${aws_ecr_repository.ingest.repository_url}@${data.aws_ecr_image.ingest.image_digest}"
}

# -- Poller role: lake read/write under raw/ curated/ manifests/, its metric, its logs. ------
# It deletes nothing: raw/ is immutable and curated/ only ever gains postings.

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ingest" {
  name               = "${var.ingest_name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "ingest" {
  statement {
    sid       = "ListLake"
    actions   = ["s3:ListBucket"]
    resources = [var.lake_bucket_arn]
  }

  statement {
    sid     = "WriteLake"
    actions = ["s3:GetObject", "s3:PutObject"]
    resources = [
      "${var.lake_bucket_arn}/${var.raw_prefix}/*",
      "${var.lake_bucket_arn}/${var.curated_prefix}/*",
      "${var.lake_bucket_arn}/${var.manifests_prefix}/*",
    ]
  }

  statement {
    sid       = "PutFreshnessMetric"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = [var.metric_namespace]
    }
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.ingest.arn}:*"]
  }
}

resource "aws_iam_role_policy" "ingest" {
  name   = "${var.ingest_name}-lambda"
  role   = aws_iam_role.ingest.id
  policy = data.aws_iam_policy_document.ingest.json
}

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${var.ingest_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "ingest" {
  function_name = var.ingest_name
  description   = "Polls Open-Meteo forecasts into the weather lake; payload {\"product\": ...} or {}"
  role          = aws_iam_role.ingest.arn
  package_type  = "Image"
  image_uri     = local.image_uri
  architectures = ["arm64"]
  memory_size   = var.lambda_memory_mb
  timeout       = var.lambda_timeout_s

  environment {
    variables = { LAKE_ROOT = "s3://${var.lake_bucket}" }
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.ingest.name
  }

  depends_on = [aws_iam_role_policy.ingest]
}

# The schedules invoke asynchronously. Lambda's defaults (two retries of a failed run, throttled
# events kept for six hours) turn a slow source into a backlog of stale runs; the next scheduled
# poll is the retry, so failed and stale events are dropped.
resource "aws_lambda_function_event_invoke_config" "ingest" {
  function_name                = aws_lambda_function.ingest.function_name
  maximum_retry_attempts       = 0
  maximum_event_age_in_seconds = 900
}

# -- Compaction: its own role, the only one that may delete, and only under curated/ ---------

resource "aws_iam_role" "compact" {
  name               = "${var.compact_name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "compact" {
  statement {
    sid       = "ListCurated"
    actions   = ["s3:ListBucket"]
    resources = [var.lake_bucket_arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.curated_prefix}/*"]
    }
  }

  statement {
    sid       = "RewriteCurated"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${var.lake_bucket_arn}/${var.curated_prefix}/*"]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.compact.arn}:*"]
  }
}

resource "aws_iam_role_policy" "compact" {
  name   = "${var.compact_name}-lambda"
  role   = aws_iam_role.compact.id
  policy = data.aws_iam_policy_document.compact.json
}

resource "aws_cloudwatch_log_group" "compact" {
  name              = "/aws/lambda/${var.compact_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "compact" {
  function_name = var.compact_name
  description   = "Merges curated files older than an hour into one file per partition"
  role          = aws_iam_role.compact.arn
  package_type  = "Image"
  image_uri     = local.image_uri
  architectures = ["arm64"]
  memory_size   = 1024
  timeout       = 600

  image_config {
    command = ["ingest.handler.compact"]
  }

  environment {
    variables = { LAKE_ROOT = "s3://${var.lake_bucket}" }
  }

  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.compact.name
  }

  depends_on = [aws_iam_role_policy.compact]
}

resource "aws_lambda_function_event_invoke_config" "compact" {
  function_name                = aws_lambda_function.compact.function_name
  maximum_retry_attempts       = 0
  maximum_event_age_in_seconds = 900 # the next hourly run merges whatever this one missed
}

# -- Schedules: one per product (cron from config.yaml, Central time), hourly compaction -----

resource "aws_scheduler_schedule_group" "weather" {
  name = var.schedule_group
}

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [var.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.ingest_name}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.ingest.arn, aws_lambda_function.compact.arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "${var.ingest_name}-scheduler"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "product" {
  for_each = var.products

  name                         = "${var.ingest_name}-${each.key}"
  group_name                   = aws_scheduler_schedule_group.weather.name
  description                  = "poll ${each.key}"
  schedule_expression          = each.value.schedule
  schedule_expression_timezone = var.schedule_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.ingest.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ product = each.key })

    retry_policy {
      maximum_retry_attempts       = 0
      maximum_event_age_in_seconds = 900
    }
  }
}

resource "aws_scheduler_schedule" "compact" {
  name                         = var.compact_name
  group_name                   = aws_scheduler_schedule_group.weather.name
  description                  = "merge small curated files"
  schedule_expression          = var.compact_schedule
  schedule_expression_timezone = var.schedule_timezone

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.compact.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({})

    retry_policy {
      maximum_retry_attempts       = 0
      maximum_event_age_in_seconds = 900
    }
  }
}
