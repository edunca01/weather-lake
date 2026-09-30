output "lake_bucket" {
  value = aws_s3_bucket.lake.bucket
}

output "lake_bucket_arn" {
  value = aws_s3_bucket.lake.arn
}

output "lake_read_policy_arn" {
  value = aws_iam_policy.lake_read.arn
}

output "ssm_parameters" {
  value = sort([for p in aws_ssm_parameter.published : p.name])
}
