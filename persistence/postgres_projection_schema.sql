-- PostgreSQL-ready read-model tables for multi-enterprise projections.
-- Filesystem artifacts remain authoritative until postgres_authoritative is enabled.

CREATE TABLE IF NOT EXISTS order_lifecycle_orders (
    run_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    exchange_id TEXT NOT NULL,
    order_id TEXT NOT NULL,
    seller_id TEXT,
    buyer_id TEXT,
    product_id TEXT,
    quantity DOUBLE PRECISION,
    value DOUBLE PRECISION,
    status TEXT,
    planned_delivery_round INTEGER,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, round_id, order_id)
);

CREATE INDEX IF NOT EXISTS idx_order_lifecycle_orders_run_round
    ON order_lifecycle_orders(run_id, round_id);

CREATE TABLE IF NOT EXISTS topology_nodes (
    run_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    enterprise_id TEXT NOT NULL,
    name TEXT,
    tier INTEGER,
    role_tags JSONB NOT NULL,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, round_id, enterprise_id)
);

CREATE TABLE IF NOT EXISTS topology_edges (
    run_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    supplier_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    valid BOOLEAN NOT NULL,
    compatible_products JSONB NOT NULL,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, round_id, supplier_id, customer_id)
);

CREATE TABLE IF NOT EXISTS enterprise_daily_metrics (
    run_id TEXT NOT NULL,
    scenario_id TEXT NOT NULL,
    round_id INTEGER NOT NULL,
    enterprise_id TEXT NOT NULL,
    cash DOUBLE PRECISION,
    net_profit DOUBLE PRECISION,
    bought_order_count INTEGER,
    sold_order_count INTEGER,
    bought_quantity DOUBLE PRECISION,
    sold_quantity DOUBLE PRECISION,
    bought_value DOUBLE PRECISION,
    sold_value DOUBLE PRECISION,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (run_id, round_id, enterprise_id)
);
