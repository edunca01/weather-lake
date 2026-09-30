# One alarm, whatever the number of products. Every poll publishes the minutes since the newest
# posting (the maximum over products). Content that stops changing means the source is stale;
# no datapoints mean the poller stopped, so missing data breaches too.

resource "aws_cloudwatch_metric_alarm" "data_stale" {
  alarm_name          = var.alarm_name
  alarm_description   = "No new weather forecast for over ${var.stale_after_min} min, or the poller stopped publishing. Check /aws/lambda/${var.ingest_function_name}."
  namespace           = var.metric_namespace
  metric_name         = "PostingAgeMinutes"
  statistic           = "Maximum"
  period              = 3600
  evaluation_periods  = 2
  datapoints_to_alarm = 2
  threshold           = var.stale_after_min
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = var.alarm_topic_arns
  ok_actions          = var.alarm_topic_arns
}
