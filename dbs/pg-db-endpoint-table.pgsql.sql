CREATE TABLE IF NOT EXISTS endpoint_tb (
  endpoint_id           text PRIMARY KEY,
  tenant_id             text,
  name                  text,
  description           text,

  endpoint_type         int,
  gateway_id            int,

  application_id        text,
  app_version_id        text,
  device_alternate_id   text,

  is_default_group      boolean,
  is_deactivated        boolean,

  external_id           text,
  machine_class_id      text,
  designator            text,

  machine_ddis          text,          -- store repeated ints safely
  original_endpoint_id  text,
  paired_tenant_id      text,
  pairing_id            text,
  is_subscribed         boolean,
  virtual_cu_owner_id   text,
  version_tag           text,

  reason                text,
  event_time            timestamptz,

  kafka_topic           text,
  kafka_partition       int,
  kafka_offset          bigint,
  kafka_ts              timestamptz
);