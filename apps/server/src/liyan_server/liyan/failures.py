"""Why one 立言 run produced no 立言文章.

Like its 知言 counterpart, a failure carries a stable code, a message the user
may read, and internal detail that must never reach the browser — plus what the
provider invoiced getting there. 立言 sends no tools, so its bill is smaller and
far more predictable than 知言's; it is recorded for the same reason all the
same, which is that a cost nobody wrote down cannot be reconciled later.
"""

from liyan_server.provider_usage import ProviderUsage


class LiyanRunFailure(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        internal_error: str | None = None,
        *,
        usage: ProviderUsage | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.internal_error = internal_error
        #: What the provider invoiced for the call this failure ended, if it got
        #: far enough to be told. `None` means nothing billable happened.
        self.usage = usage
        self.model = model
