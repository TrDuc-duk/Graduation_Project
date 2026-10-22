"""Thiết bị: mạng LoRa, Gateway, node, cảm biến, liên kết node–Gateway (database_design 5.2).

Revision ID: 0002_devices
Revises: 0001_base
"""

from alembic import op

revision = "0002_devices"
down_revision = "0001_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE lora_networks (
      id          smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      code        text NOT NULL UNIQUE CHECK (code ~ '^[a-z0-9_-]{1,30}$'),
      name        text NOT NULL,
      note        text,
      created_at  timestamptz NOT NULL DEFAULT now(),
      updated_at  timestamptz NOT NULL DEFAULT now()
    );
    CREATE TRIGGER trg_lora_networks_updated_at BEFORE UPDATE ON lora_networks
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
    INSERT INTO lora_networks (code, name) VALUES ('default', 'Mạng mặc định');

    CREATE TABLE gateways (
      id                       text PRIMARY KEY CHECK (id ~ '^[A-Za-z0-9_-]{1,15}$'),
      lora_network_id          smallint NOT NULL REFERENCES lora_networks(id),
      name                     text NOT NULL,
      location_desc            text,
      geom                     geometry(Point, 4326),
      status                   text NOT NULL DEFAULT 'pending'
                               CHECK (status IN ('pending','active','disabled','retired')),
      registered_via           text NOT NULL CHECK (registered_via IN ('provision','auto_discovered','admin')),
      connectivity             text NOT NULL DEFAULT 'unknown' CHECK (connectivity IN ('online','offline','unknown')),
      sends_msg_id             boolean,
      last_seen_at             timestamptz,
      last_heartbeat_at        timestamptz,
      last_telemetry_at        timestamptz,
      telemetry_rejected_since timestamptz,
      last_ip                  inet,
      approved_at              timestamptz,
      approved_by              bigint REFERENCES users(id) ON DELETE SET NULL,
      first_data_at            timestamptz,
      retired_at               timestamptz,
      created_at               timestamptz NOT NULL DEFAULT now(),
      updated_at               timestamptz NOT NULL DEFAULT now(),
      CHECK ((status = 'retired') = (retired_at IS NOT NULL))
    );
    CREATE INDEX ix_gateways_geom    ON gateways USING gist (geom);
    CREATE INDEX ix_gateways_network ON gateways (lora_network_id);
    CREATE TRIGGER trg_gateways_updated_at BEFORE UPDATE ON gateways
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE SEQUENCE station_code_seq;

    CREATE TABLE nodes (
      id                   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
      station_code         text NOT NULL UNIQUE CHECK (station_code ~ '^ST[0-9]{3,}$'),
      lora_network_id      smallint NOT NULL REFERENCES lora_networks(id),
      lora_addr            smallint NOT NULL CHECK (lora_addr BETWEEN 1 AND 255),
      device_code          text GENERATED ALWAYS AS ('NODE_' || lpad(lora_addr::text, 3, '0')) STORED,
      name                 text NOT NULL,
      address              text,
      district             text,
      geom                 geometry(Point, 4326),
      environment          text NOT NULL DEFAULT 'outdoor'
                           CHECK (environment IN ('outdoor','roadside','indoor','other')),
      home_gateway_id      text REFERENCES gateways(id) ON DELETE SET NULL,
      status               text NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending','active','maintenance','retired')),
      registered_via       text NOT NULL CHECK (registered_via IN ('provision','auto_discovered','admin')),
      is_public            boolean NOT NULL DEFAULT true,
      forecast_enabled     boolean NOT NULL DEFAULT true,
      is_simulated         boolean NOT NULL DEFAULT false,
      power_source         text NOT NULL DEFAULT 'unknown' CHECK (power_source IN ('battery','external','unknown')),
      expected_interval_s  integer CHECK (expected_interval_s BETWEEN 5 AND 86400),
      interval_locked      boolean NOT NULL DEFAULT false,
      observed_interval_s  integer,
      observed_interval_iqr_ratio real,
      offline_after_s      integer CHECK (offline_after_s > 0),
      connectivity         text NOT NULL DEFAULT 'unknown' CHECK (connectivity IN ('online','offline','unknown')),
      last_seen_at         timestamptz,
      last_heard_at        timestamptz,
      last_measurement_at  timestamptz,
      last_msg_id          smallint CHECK (last_msg_id BETWEEN 0 AND 255),
      lost_packets_24h     integer,
      last_gateway_id      text,
      battery_pct          smallint CHECK (battery_pct BETWEEN 0 AND 100),
      approved_at          timestamptz,
      approved_by          bigint REFERENCES users(id) ON DELETE SET NULL,
      first_data_at        timestamptz,
      retired_at           timestamptz,
      created_at           timestamptz NOT NULL DEFAULT now(),
      updated_at           timestamptz NOT NULL DEFAULT now(),
      CHECK ((status = 'retired') = (retired_at IS NOT NULL)),
      CHECK (NOT interval_locked OR expected_interval_s IS NOT NULL)
    );
    CREATE UNIQUE INDEX ux_nodes_network_addr_live ON nodes (lora_network_id, lora_addr) WHERE status <> 'retired';
    CREATE INDEX ix_nodes_network_addr ON nodes (lora_network_id, lora_addr, retired_at DESC);
    CREATE INDEX ix_nodes_geom         ON nodes USING gist (geom);
    CREATE INDEX ix_nodes_status       ON nodes (status);
    CREATE INDEX ix_nodes_home_gateway ON nodes (home_gateway_id);
    CREATE TRIGGER trg_nodes_updated_at BEFORE UPDATE ON nodes
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE TABLE node_sensors (
      node_id        integer NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
      sensor         text NOT NULL CHECK (sensor IN ('pms7003','aht10','ccs811')),
      enabled        boolean NOT NULL DEFAULT true,
      health         text NOT NULL DEFAULT 'unknown' CHECK (health IN ('ok','warming_up','error','unknown')),
      last_ok_at     timestamptz,
      last_error_at  timestamptz,
      error_streak   integer NOT NULL DEFAULT 0,
      note           text,
      updated_at     timestamptz NOT NULL DEFAULT now(),
      PRIMARY KEY (node_id, sensor)
    );
    CREATE TRIGGER trg_node_sensors_updated_at BEFORE UPDATE ON node_sensors
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    CREATE TABLE node_gateway_links (
      node_id        integer NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
      gateway_id     text NOT NULL REFERENCES gateways(id) ON DELETE CASCADE,
      first_seen_at  timestamptz NOT NULL DEFAULT now(),
      last_seen_at   timestamptz NOT NULL DEFAULT now(),
      packet_count   bigint NOT NULL DEFAULT 0,
      PRIMARY KEY (node_id, gateway_id)
    );
    CREATE INDEX ix_node_gateway_links_gateway ON node_gateway_links (gateway_id);
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE node_gateway_links, node_sensors, nodes, gateways, lora_networks;
    DROP SEQUENCE station_code_seq;
    """)
