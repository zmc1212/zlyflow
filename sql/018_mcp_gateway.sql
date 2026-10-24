-- 2026-10-20: additive MCP OAuth, references and idempotent submission records.
CREATE TABLE IF NOT EXISTS mcp_gateway_records (
    id VARCHAR(160) CHARACTER SET ascii COLLATE ascii_bin PRIMARY KEY,
    kind VARCHAR(32) NOT NULL,
    owner_id VARCHAR(64) NOT NULL DEFAULT '',
    parent_id VARCHAR(160) CHARACTER SET ascii COLLATE ascii_bin NOT NULL DEFAULT '',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    payload_json LONGTEXT NOT NULL,
    created_at DOUBLE NOT NULL,
    updated_at DOUBLE NOT NULL,
    KEY idx_mcp_owner (owner_id, kind, created_at),
    KEY idx_mcp_parent (parent_id, kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
