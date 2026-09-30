# The whole stack from one root: storage, compute and the freshness alarm. config.yaml is the
# single source of products and schedules, so adding a product never touches Terraform.

data "aws_caller_identity" "current" {}

locals {
  config   = yamldecode(file("${path.module}/${var.config_path}"))
  products = { for k, p in local.config.products : k => { schedule = p.schedule } }

  # The version the deployed code writes, read from the library so it cannot drift.
  contract_version = regex(
    "CONTRACT_VERSION: Final = \"([^\"]+)\"",
    file("${path.module}/${var.contract_path}"),
  )[0]

  stale_after_min = max([for p in local.config.products : p.stale_after_min]...)
}

module "storage" {
  source = "../modules/storage"

  name_prefix      = var.name_prefix
  account_id       = data.aws_caller_identity.current.account_id
  region           = var.region
  contract_version = local.contract_version
}

module "compute" {
  source = "../modules/compute"

  account_id      = data.aws_caller_identity.current.account_id
  lake_bucket     = module.storage.lake_bucket
  lake_bucket_arn = module.storage.lake_bucket_arn
  image_tag       = var.image_tag
  products        = local.products
}

module "observability" {
  source = "../modules/observability"

  ingest_function_name = module.compute.ingest_function_name
  stale_after_min      = local.stale_after_min
  alarm_topic_arns     = var.alarm_topic_arns
}
