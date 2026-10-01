output "ecr_repository_url" {
  value = aws_ecr_repository.ingest.repository_url
}

output "ecr_repository_arn" {
  value = aws_ecr_repository.ingest.arn
}

output "image_uri" {
  description = "The image, pinned by digest, that the poller runs."
  value       = local.image_uri
}

output "ingest_function_name" {
  value = aws_lambda_function.ingest.function_name
}

output "schedules" {
  value = { for k, s in aws_scheduler_schedule.product : k => s.schedule_expression }
}

output "compact_function_name" {
  value = aws_lambda_function.compact.function_name
}
