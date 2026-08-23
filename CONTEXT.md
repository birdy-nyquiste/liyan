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

**知言报告**:
The trustworthy, immutable analysis produced for one source revision, covering source context, facts, viewpoints, logic, intent, and evidence.
_Avoid_: 分析结果, 事实核查报告

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
