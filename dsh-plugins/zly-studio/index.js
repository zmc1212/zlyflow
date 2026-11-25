/**
 * Host half of the ZLY AI Video Studio bundle.
 *
 * The panel, locale resources and embedded studio live in the Client module
 * (`client.js`). The Host half stays intentionally small until the account and
 * billing bridge lands; the configured origin is currently read by the Client
 * module from its own setting.
 */

/** @param {import('@deepseek-ai/cordis').Context} _ctx */
export function apply() {}