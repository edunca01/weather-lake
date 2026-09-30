output "lake_bucket" {
  value = module.storage.lake_bucket
}

output "lake_read_policy_arn" {
  value = module.storage.lake_read_policy_arn
}

output "ssm_parameters" {
  value = module.storage.ssm_parameters
}

output "ecr_repository_url" {
  value = module.compute.ecr_repository_url
}

output "image_uri" {
  value = module.compute.image_uri
}

output "schedules" {
  value = module.compute.schedules
}

output "alarm_name" {
  value = module.observability.alarm_name
}
