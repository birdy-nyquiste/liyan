# Bound 知言 recovery with server-owned retry timing

Function Spec §5.3–5.4 gives one 知言 生成 target a fixed budget: the initial
operation runs at most twice, the second run created automatically and only when
the first failed for a reason another run could survive; after that every run is
a manual retry, at most two in any rolling 30 minutes, with the next allowed
moment decided by the server. 立言 opens only when every source Revision of the
current 任务版本 holds an accepted 知言报告.

Three facts an Execution did not previously carry make this enforceable rather
than advisory. `origin` records whether a run is the `initial` operation, its one
`automatic` recovery, or a user's `manual` retry, so the rolling window counts
only what the user actually spent and the automatic attempt cannot be spent
twice. `retry_allowed_at` records the backoff the real failure earned.
`stale_result` holds provider output that arrived too late to matter. The whole
policy — which failure codes are worth another run, how long each backs off, and
how the window combines with the backoff — is one dependency-free module,
`zhiyan/recovery`, so the API and the worker cannot drift apart.

The automatic attempt is created by the worker, inside the same transaction that
records the failure, because only there is the real failure reason known. The
worker then dispatches it, so a queue outage fails the follow-up visibly instead
of leaving a queued row nothing will ever claim.

Cancellation costs a target nothing: a cancelled run never triggers the automatic
attempt and never sets a backoff. It still spends the call frequency a manual
retry consumed, because the provider was already asked. Provider output that
arrives after a cancellation, or after another run's report was already accepted,
is written to that Execution's `stale_result` and nowhere else: it is available
for tracing, is never returned by any endpoint, and can never become a 知言报告.

Redaction belongs to the 知言 boundary, not to a view. The real failure code and
the original provider error stay on the Execution for operators, while every
failed run leaves that boundary as `busy` / 服务繁忙，请重试; a cancellation keeps its
own wording because it is the user's own act. The client is otherwise told only
`allowed`, `remaining`, and `allowed_at`. Because the allowance is derived from
stored Executions on every request, a reload, a second tab, or a direct `POST`
cannot shorten a countdown or buy an extra retry; the manual-retry endpoint
answers `429` with `Retry-After` when the target must wait, and the workbench
treats that answer as the countdown speaking rather than as a fault.

Confirmation queues one run per source Revision after — never inside — the task
creation transaction, matching Technical Spec §5.1. Queueing skips any Revision
that already holds a report or a run, so a client replaying the same idempotent
confirmation starts nothing new, and a queue that refuses the work leaves the
formal task created with a retryable failed run.
