-- 2026-11-19: 企业成员额度上限（企业积分集中充值、按成员分配使用上限）。
-- 背景：企业钱包已统一充值与结算，但成员消费只受企业总余额约束，无法按人分配额度。
-- 本表为企业 + 成员维度的额度配置：
--   period = none（不限制，默认）/ monthly（北京时间自然月）/ total（累计）
--   credit_limit 为积分上限（100 积分 = 1 元）；用量由 enterprise_credit_transactions
--   的 consume - refund 实时聚合，不额外维护已用字段，退款自动回冲。
-- 兼容性：新增独立表，不改 users / enterprise_credit_accounts / 流水表；无配置行即不限制。
-- 回滚方式：DROP TABLE IF EXISTS enterprise_member_quotas;
--   企业钱包、模型策略与既有计费路径不受影响。

CREATE TABLE IF NOT EXISTS enterprise_member_quotas (
    enterprise_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    period VARCHAR(16) NOT NULL DEFAULT 'none',
    credit_limit INTEGER NOT NULL DEFAULT 0,
    updated_at VARCHAR(64) NOT NULL,
    PRIMARY KEY (enterprise_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
