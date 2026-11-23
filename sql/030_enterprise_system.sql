-- 2026-11-19: 企业管理体系（企业入驻 / 企业积分钱包 / 成员归属 / 模型访问策略）。
-- 背景：平台开始对外按企业入驻。企业作为一个结算与管控单元：
-- 1) enterprises               企业主档（名称/编码/上级企业/联系人/状态），账号通过 users.enterprise_id 归属企业；
--    parent_id 表达集团-子公司层级（可为空表示顶级企业），仅作组织架构与账号归属过滤，
--    不改变计费口径：每个企业仍是独立钱包与独立模型策略。
-- 2) enterprise_credit_accounts 每企业一行积分钱包（整数积分，锚定 100 积分 = 1 元）；
-- 3) enterprise_credit_transactions 企业积分流水：充值/调整/成员消费/退款，user_id 记录消费人，
--    用于「按企业查看用量」与「统计企业下每个人员的积分用量」；
-- 4) enterprise_model_policies  企业模型访问策略：model_kind = video / image / llm / vlm，
--    mode = all（全部开放）/ whitelist（仅开放 models_json 清单）/ none（全部关闭）。
--    未配置的类型默认 all，与既有「不限制」行为兼容。
-- 计费联动：预扣与按次扣费使用用户当前结算钱包。挂起任务的退款回到预扣的钱包。
-- 消费流水的 user_id 仍记录实际使用人，保证成员粒度用量可统计。
-- 兼容性：全部 CREATE TABLE IF NOT EXISTS 幂等；users.enterprise_id 由 AuthStore.initialize()
-- ensure_column 平滑补列（同时补进 001 基线建表）。独立于现有业务表，停用企业管理不影响计费。
-- 回滚方式：删表
--   DROP TABLE IF EXISTS enterprise_model_policies;
--   DROP TABLE IF EXISTS enterprise_credit_transactions;
--   DROP TABLE IF EXISTS enterprise_credit_accounts;
--   DROP TABLE IF EXISTS enterprises;
--   并将 users.enterprise_id 置 NULL（列保留无害）。

CREATE TABLE IF NOT EXISTS enterprises (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    code VARCHAR(64) NULL,
    parent_id VARCHAR(64) NULL,
    contact_name VARCHAR(80) NULL,
    contact_phone VARCHAR(64) NULL,
    notes VARCHAR(512) NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_by VARCHAR(64) NULL,
    created_at VARCHAR(64) NOT NULL,
    updated_at VARCHAR(64) NOT NULL,
    UNIQUE KEY uk_enterprises_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS enterprise_credit_accounts (
    enterprise_id VARCHAR(64) NOT NULL PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0,
    total_recharged INTEGER NOT NULL DEFAULT 0,
    total_consumed INTEGER NOT NULL DEFAULT 0,
    updated_at VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS enterprise_credit_transactions (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    enterprise_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NULL,
    delta INTEGER NOT NULL,
    type VARCHAR(32) NOT NULL,
    reason VARCHAR(512) NULL,
    price_key VARCHAR(128) NULL,
    ref_type VARCHAR(32) NULL,
    ref_id VARCHAR(128) NULL,
    balance_after INTEGER NOT NULL,
    actor_user_id VARCHAR(64) NULL,
    meta_json TEXT NULL,
    created_at VARCHAR(64) NOT NULL,
    INDEX idx_ent_credit_tx_created (enterprise_id, created_at),
    INDEX idx_ent_credit_tx_user (enterprise_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS enterprise_model_policies (
    enterprise_id VARCHAR(64) NOT NULL,
    model_kind VARCHAR(32) NOT NULL,
    mode VARCHAR(16) NOT NULL DEFAULT 'all',
    models_json TEXT NULL,
    updated_at VARCHAR(64) NOT NULL,
    PRIMARY KEY (enterprise_id, model_kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
