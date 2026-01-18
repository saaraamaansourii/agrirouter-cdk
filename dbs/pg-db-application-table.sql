CREATE TABLE IF NOT EXISTS application_tb (
  tenant_id        text NOT NULL,
  name             text NOT NULL,

  description      text,
  type             text,          -- proto field "type" is STRING in your Flink schema
  brand            text,
  logo_url         text,
  support_url      text,
  deep_url         text,
  public_key       text,
  version_tag      text,
  application_type int,           -- enum stored as int

  redirect_url     text,          -- repeated string

  reason           text,
  event_time       timestamptz,

  kafka_topic      text,
  kafka_partition  int,
  kafka_offset     bigint,
  kafka_ts         timestamptz,

  PRIMARY KEY (tenant_id, name)
);