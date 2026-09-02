# 立言阁

立言阁 MVP covers the workbench and server-side domain for turning submitted sources into trustworthy analysis and a user-directed article that may be published independently.

## Language

**来源**:
One user-submitted body of material within a 立言任务. A task version contains one to three sources.
_Avoid_: 投稿文章, 素材

**任务创建会话**:
A temporary context in which a user submits, previews, and confirms sources before a formal 立言任务 exists. It is not a recoverable draft.
_Avoid_: 草稿任务, 临时任务

**立言任务**:
The enduring user-owned context that organizes sources, 知言 reports, and 立言 articles across versions.
_Avoid_: 内容任务, 项目

**任务版本**:
An immutable snapshot of the sources belonging to a 立言任务 at a point in its history.
_Avoid_: 文章版本, Revision

**来源编辑会话**:
A temporary set of proposed source additions, replacements, edits, and deletions within an existing 立言任务. Only saving it creates a durable task version; leaving it unfinished discards its changes.
_Avoid_: 任务版本, 可恢复草稿

**主题**:
The single subject a 任务版本 is about: one line of plain text, at most 80 characters, confirmed before the 立言任务 exists and changed only by producing a new 任务版本. It may be absent, and absent is a confirmation rather than an omission.
_Avoid_: 标题, 选题, 立意

**主题候选**:
One of exactly three 主题 an Agent offers from the 来源 in hand — those of a 任务创建会话, or those of a 来源编辑会话 as the writer currently has them — each with one sentence saying why it fits them. Pressing one fills the 主题 box; it is not a 主题 until the user saves or confirms with it.
_Avoid_: 推荐主题, 主题建议

**知言报告**:
The trustworthy, immutable analysis produced for one source revision, covering source context, facts, viewpoints, logic, intent, and evidence.
_Avoid_: 分析结果, 事实核查报告

**主题知言报告**:
The immutable analysis produced for one 主题, covering the subject's landscape, externally established facts, the spread of viewpoints, where they disagree, and the angles the 来源 of its 任务版本 leave out. It is reference material: it gates 立言 but enters an article only where the user cites it.
_Avoid_: 主题分析, 背景报告

**事实结论**:
The verdict a 知言报告 assigns to one externally verifiable claim. It is exactly one of 有证据支持, 有证据反驳, 部分准确, 存在争议, or 暂无法核实. The four deterministic verdicts must each cite evidence the run actually opened; 暂无法核实 is what a run states when no reliable material was found.
_Avoid_: 事实评分, 可信度, 置信度

**立言指令**:
The user's optional editorial direction for generating or revising a 立言文章. It may override the default editorial treatment of conclusions in a 知言报告.
_Avoid_: 用户 Prompt, 默认立言指令

**立言文章**:
A task-version-level article whose editorial position remains controlled by the user rather than by the conclusions of 知言.
_Avoid_: 知言文章, 生成结果

**Working Copy**:
The mutable, unsaved state of a 立言文章 while the user is editing or regenerating it. It is not part of article history until explicitly saved.
_Avoid_: Revision, 自动保存版本

**文章 Revision**:
An immutable snapshot created only when the user explicitly saves a 立言文章.
_Avoid_: 任务版本, 自动保存版本

**发布任务**:
An independent attempt to submit the locked snapshot of an eligible article Revision to a publication target. For the MVP Blog target, returning a Preview URL is the terminal successful outcome; it does not complete or finalize the 立言任务.
_Avoid_: 发布状态, 定稿

**发布目标**:
A server-configured destination that specific users are authorized to publish to. It grants access only: the author name shown on the published item is the user's to give, not the target's.
_Avoid_: 平台账号, Blog 配置

**发布作者名**:
The author name a user types when confirming a 发布任务, sent to the platform and displayed there. The platform treats one name as one author across submissions, so it is trimmed before it is locked into the snapshot.
_Avoid_: 作者映射, 用户昵称

**Blog Preview**:
A password-protected Blog draft and Preview URL created by a successful MVP 发布任务. Any subsequent action by the user in Blog is outside 立言阁.
_Avoid_: 已发布文章, 公开文章

**公开发布**:
Any later Blog-side action through which the user makes a Blog Preview publicly available. It is outside 立言阁.
_Avoid_: Preview 创建, 提交成功

**结果未知**:
The terminal outcome of a 发布任务 whose Blog submission may have succeeded but did not return a confirmed Preview URL. It cannot be retried by 立言阁; any reconciliation happens outside the product.
_Avoid_: 发布失败, 可重试失败

**额度**:
The unit of paid capacity. Every metered act consumes 额度; what one 额度 is worth in money is 立言阁's own, and only the count is shown.
_Avoid_: 点数, 积分, 次数, 余额

**额度包**:
What a user buys: one price for one amount of 额度. The price is the user's side of the exchange; the amount is 立言阁's.
_Avoid_: 套餐, 订阅, 会员

**赠送额度**:
额度 granted rather than bought — what a new user is given once on signing up, and any later promotion. A refund never reclaims them.
_Avoid_: 免费额度, 试用额度

**购买额度**:
额度 a user bought. A refund or a payment dispute may reclaim them.
_Avoid_: 充值额度, 付费额度

**使用记录**:
The append-only record of every 额度 赠送, 购买, 预扣, and 结算. A user's remaining 额度 is read from it and never stored beside it.
_Avoid_: 账单, 消费记录, 流水

**预扣**:
The 额度 taken when work is admitted, before it has produced anything, at what that work is expected to cost. It is what makes remaining 额度 answer "what may I still start" rather than "what have I already spent".
_Avoid_: 冻结, 预留, 预占

**结算**:
The correction written once work reaches a terminal state, being the difference between its 预扣 and what it actually cost. It returns the excess when the estimate was high and collects the shortfall when it was low. Work that produced nothing settles to zero.
_Avoid_: 归还, 补扣, 退款 (that is Stripe's, and returns money)

**付费用户**:
A user who has bought 额度 at least once. It is what authorizes URL and file 来源 capture; a user who has not is limited to 来源 they paste. It is not a plan, a tier, or a subscription.
_Avoid_: 会员, 订阅用户, Pro 用户, 套餐

**立言阁浏览器插件**:
The browser client that turns a page the user is reading into 来源 of a new 立言任务. It collects up to three of them in a 任务创建会话 and confirms them together. It submits the page's address for the server to capture and never reads the page itself, and it does not edit a 立言任务 once created — that is the workbench's.
_Avoid_: 扩展, Chrome 扩展, 扩展程序, 采集器
