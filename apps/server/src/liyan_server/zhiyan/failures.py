"""Why one 知言 run produced no 知言报告.

Transport and acceptance fail for different reasons but carry the same three
things: a stable code, a message the user may read, and internal detail that must
never reach the browser. One base type lets a run handle both in one place.

A failure also carries what the run consumed getting there. That is not
bookkeeping pedantry: the failures that cost the most are the ones raised
*inside* the adapter, after a provider call has returned and been invoiced but
before there is any result object to hand back — a run that searched twenty
times and returned no report is the single most expensive thing this system
does, and without this it recorded nothing at all.
"""

from liyan_server.provider_usage import ProviderUsage


class ZhiyanRunFailure(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        internal_error: str | None = None,
        *,
        usage: ProviderUsage | None = None,
        model: str | None = None,
        search_calls: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.internal_error = internal_error
        #: What the provider invoiced for the call(s) this failure ended, if it
        #: got far enough to be told. `None` means nothing billable happened.
        self.usage = usage
        self.model = model
        self.search_calls = search_calls

