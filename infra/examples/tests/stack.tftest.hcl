# The example root against a mocked AWS provider: nothing is created and no credentials are
# needed.

mock_provider "aws" {
  source = "./tests"
}

variables {
  name_prefix = "test"
}

run "defaults" {
  command = apply

  assert {
    condition     = output.lake_bucket == "test-weather-123456789012"
    error_message = "the bucket is <prefix>-weather-<account id>"
  }

  assert {
    condition = alltrue([
      for k, p in yamldecode(file("../../config.yaml")).products : output.schedules[k] == p.schedule
    ])
    error_message = "every product in config.yaml gets its schedule verbatim"
  }

  assert {
    condition     = length(output.schedules) == length(yamldecode(file("../../config.yaml")).products)
    error_message = "one schedule per product"
  }

  assert {
    condition     = endswith(output.image_uri, "@sha256:0000000000000000000000000000000000000000000000000000000000000000")
    error_message = "the Lambda runs an image pinned by digest, never a tag"
  }

  assert {
    condition = output.ssm_parameters == tolist([
      "/weather-lake/contract_version",
      "/weather-lake/lake_bucket",
      "/weather-lake/lake_bucket_arn",
      "/weather-lake/lake_read_policy_arn",
      "/weather-lake/region",
    ])
    error_message = "consumers find the lake through these parameters"
  }

  assert {
    condition     = output.alarm_name == "weather-data-stale"
    error_message = "exactly one alarm"
  }

  assert {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", local.contract_version))
    error_message = "the contract version is read from the library as SemVer"
  }
}

run "alarm_notifies_the_given_topics" {
  command = apply

  module {
    source = "../modules/observability"
  }

  variables {
    ingest_function_name = "weather-ingest"
    stale_after_min      = 240
    alarm_topic_arns     = ["arn:aws:sns:us-east-1:123456789012:alerts"]
  }

  assert {
    condition = (
      aws_cloudwatch_metric_alarm.data_stale.alarm_actions == toset(["arn:aws:sns:us-east-1:123456789012:alerts"])
      && aws_cloudwatch_metric_alarm.data_stale.treat_missing_data == "breaching"
      && aws_cloudwatch_metric_alarm.data_stale.threshold == 240
    )
    error_message = "the alarm notifies the given topics, and a stopped poller breaches"
  }
}

run "no_async_retries" {
  command = apply

  module {
    source = "../modules/compute"
  }

  variables {
    account_id      = "123456789012"
    lake_bucket     = "test-weather"
    lake_bucket_arn = "arn:aws:s3:::test-weather"
    image_tag       = "t"
    products        = { p = { schedule = "cron(25 * * * ? *)" } }
  }

  assert {
    condition = (
      aws_lambda_function_event_invoke_config.ingest.maximum_retry_attempts == 0
      && aws_scheduler_schedule.product["p"].target[0].retry_policy[0].maximum_retry_attempts == 0
    )
    error_message = "the next scheduled poll is the retry"
  }
}
