variable "ingest_function_name" {
  type = string
}

variable "stale_after_min" {
  description = "Minutes without a new posting before the lake counts as stale (the largest product threshold)."
  type        = number
}

variable "alarm_topic_arns" {
  description = "SNS topics the alarm notifies, e.g. an existing deployment's alert topics. Empty: the alarm only shows in CloudWatch."
  type        = list(string)
  default     = []
}

variable "alarm_name" {
  type    = string
  default = "weather-data-stale"
}

variable "metric_namespace" {
  type    = string
  default = "WeatherLake"
}
