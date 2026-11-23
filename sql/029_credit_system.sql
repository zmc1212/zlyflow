-- 2026-11-18: 用户积分体系（第一期：管理员手动充值）。
-- 背景：平台三类真实成本消耗（GRS 云端生图 / 云端视频 / LLM·VLM 调用）此前无任何用户级
-- 计量与结算机制。本期引入「积分账户 + 流水 + 可编辑价格表」，锚定 100 积分 = 1 元：
-- 1) credit_accounts   每用户一行余额（整数积分）与累计充值/消耗；
-- 2) credit_transactions 每笔余额变动流水（充值/调整/扣费/退款），balance_after 支持对账；
--    meta_json 记录 LLM/VLM 调用的模型、tokens 与上游成本（2026-11-20 增加，旧库由
--    JobStore.initialize() 的 ensure_column 自动补列，不阻塞历史流水）。
-- 3) credit_price_rules  计价条目表（对标市场初始值，管理端可覆盖）：
--    rule_key = cloud:<mode>（per_second，按分辨率/档位单价）、grs_image:global（按张，
--    上游 credit_cost × 换算系数）、llm:<kind> / vlm:<kind>（per_call）。
-- 计费策略：任务提交时预扣（consume），generation_items.credits_billed 记录每条预扣数，
-- 终态 FAILED/CANCELLED 时在 update_generation 事务内全额退款（refund）；本地 ComfyUI
-- 工作流不计费；所有账号（含 super_admin）一律按价格表结算，无角色豁免。价格种子行由 JobStore._seed_runtime_defaults 写入
-- （双方言共用），本文件只做 DDL。
-- 兼容性：全部 CREATE TABLE IF NOT EXISTS 幂等；generation_items 的 credits_billed /
-- credits_settled / credits_wallet_enterprise_id 列由 JobStore.initialize() 自动补齐。
-- credits_wallet_enterprise_id 为空字符串时表示个人钱包。NULL 表示历史任务未记录钱包，退款时查原流水。
-- 回滚方式：表独立于现有业务，停用计费只需将价格表 enabled 置 0；回滚删表
--   DROP TABLE IF EXISTS credit_transactions; DROP TABLE IF EXISTS credit_price_rules;
--   DROP TABLE IF EXISTS credit_accounts;  （可保留 generation_items 的积分列）

CREATE TABLE IF NOT EXISTS credit_accounts (
    user_id VARCHAR(64) NOT NULL PRIMARY KEY,
    balance INTEGER NOT NULL DEFAULT 0,
    total_recharged INTEGER NOT NULL DEFAULT 0,
    total_consumed INTEGER NOT NULL DEFAULT 0,
    updated_at VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS credit_transactions (
    id INTEGER PRIMARY KEY AUTO_INCREMENT,
    user_id VARCHAR(64) NOT NULL,
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
    INDEX idx_credit_tx_user_created (user_id, created_at),
    INDEX idx_credit_tx_ref (ref_type, ref_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS credit_price_rules (
    rule_key VARCHAR(128) NOT NULL PRIMARY KEY,
    scope VARCHAR(32) NOT NULL,
    pricing_kind VARCHAR(32) NOT NULL,
    unit_credits INTEGER NOT NULL DEFAULT 0,
    unit_by_variant TEXT NULL,
    extra_config TEXT NULL,
    enabled TINYINT(1) NOT NULL DEFAULT 1,
    note VARCHAR(256) NULL,
    updated_at VARCHAR(64) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
