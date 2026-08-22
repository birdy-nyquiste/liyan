# Do not blindly retry Blog Preview submissions

When a Blog submission may have reached the platform but its response is unknown, the 发布任务 enters 结果未知 and neither the system nor the user may retry it. The Blog v0.11 API provides neither an idempotency key nor an authenticated Preview lookup, so preserving availability through a retry creates an unacceptable risk of duplicate Previews; any reconciliation happens outside 立言阁 rather than through an MVP administrator workflow.
