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


class ArticleRejected(LiyanRunFailure):
    """An article the rules refused, carrying what would make it acceptable.

    The distinction from a plain `LiyanRunFailure` is whether anything can be
    done about it in the same run. A provider that could not be reached has
    nothing to fix; an article with a table in it has one table, and the run
    already holds everything else the writer asked for. `repair` is that
    sentence, in the language the Prompt is written in.
    """

    def __init__(
        self,
        code: str,
        message: str,
        internal_error: str | None = None,
        *,
        repair: str,
    ) -> None:
        super().__init__(code, message, internal_error)
        #: What to tell the model so it can fix this article rather than lose it.
        self.repair = repair
