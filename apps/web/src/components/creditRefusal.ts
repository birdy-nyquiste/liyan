/**
 * The two ways the server refuses work for want of 额度, in its own words.
 *
 * Mirrored from `credit_limits.py` rather than inferred from a status code,
 * because 402 answers both "you cannot afford this" and "this 来源 kind is what
 * a 付费用户 buys", and the two want different sentences beside the same button.
 * `test_credit_enforcement.py` is what keeps these strings honest on the server.
 */
export const INSUFFICIENT_CREDITS = "额度不足，购买后可继续。";
export const PAID_ONLY = "公共文章链接与上传文件需购买额度后解锁。";

/** Whether this refusal is one a purchase would fix. */
export function isCreditRefusal(message: string): boolean {
  return message === INSUFFICIENT_CREDITS || message === PAID_ONLY;
}
