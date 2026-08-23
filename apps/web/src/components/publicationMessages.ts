/**
 * What the two publishing surfaces say when the server refuses.
 *
 * The confirmation screen and 发布中心 both submit and both retry, so a message
 * that lived in one of them would drift out of step with the other. These are
 * fallbacks: when the server explains itself, its own wording is shown instead.
 */

/**
 * The target may already hold an item for this 立言任务. Not a conflict — a
 * precondition only the user can satisfy, by reading the warning and agreeing.
 */
export const PRECONDITION_FAILED = 412;

/** Only reached if the server refuses without saying why, which it should not. */
export const EXISTING_PREVIEW_WARNING =
  "该立言任务已有文章提交到这个发布目标，继续发布会新建另一条 Blog 内容。";

export const RETRY_FAILED = "重试未能提交，请稍后重试。";
