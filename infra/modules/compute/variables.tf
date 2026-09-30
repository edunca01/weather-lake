variable "account_id" {
  type = string
}

variable "lake_bucket" {
  type = string
}

variable "lake_bucket_arn" {
  type = string
}

variable "image_tag" {
  description = "Image tag the Lambda runs. Resolved to a digest at plan time, so a re-tag is a visible change."
  type        = string
}

variable "products" {
  description = "Products from config.yaml: key -> { schedule = cron(...) }."
  type        = map(object({ schedule = string }))
}

variable "metric_namespace" {
  description = "Namespace of the freshness metric the poller publishes."
  type        = string
  default     = "WeatherLake"
}

variable "image_repository" {
  type    = string
  default = "weather-ingest"
}

variable "ingest_name" {
  type    = string
  default = "weather-ingest"
}

variable "schedule_group" {
  type    = string
  default = "weather"
}

variable "schedule_timezone" {
  type    = string
  default = "America/Chicago"
}

variable "lambda_memory_mb" {
  type    = number
  default = 512
}

variable "lambda_timeout_s" {
  description = "Above the client's request budget, well below the hourly schedule."
  type        = number
  default     = 180
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "raw_prefix" {
  type    = string
  default = "raw"
}

variable "curated_prefix" {
  type    = string
  default = "curated"
}

variable "manifests_prefix" {
  type    = string
  default = "manifests"
}
