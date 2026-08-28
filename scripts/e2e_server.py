"""The real server, wired for a browser test, on a database that is thrown away.

The Playwright suite is written once and run twice: against Staging, where
everything is real, and locally, where nothing outside this machine may be
touched. This is what makes the second run possible without a second version of
the application — `create_app` already takes the two seams that stand between
立言阁 and the outside world, so the browser drives the actual FastAPI app, the
actual database, and the actual domain rules, with only the identity provider
and the paid providers replaced.

Three substitutions, and no others:

  * **JWT verification.** A browser cannot get a Supabase token without a
    Supabase project and a real mailbox. Any bearer token here resolves to one
    allowlisted writer.
  * **DeepSeek and Blog.** A local run must not spend money or create a Blog
    item. The doubles are the ones the test suite already uses, imported rather
    than copied so the two cannot drift.
  * **The queue.** Celery is replaced by a dispatcher that runs each Execution
    on a background thread the moment it is queued, so the workbench's polling
    sees exactly the transitions it sees in production, without a broker.

**This is not a way to run 立言阁.** It authenticates nobody and analyzes
nothing. It binds to localhost, it prints what it substituted, and it exists
only so `npm run test:e2e` has something to talk to.

    .venv/bin/python scripts/e2e_server.py --port 8099
"""

import argparse
import sys
import tempfile
import threading
from pathlib import Path
from uuid import UUID

import uvicorn

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# The doubles live with the tests because that is where they are maintained.
# Copying them here would give the browser suite its own DeepSeek, free to
# disagree with the one every other test uses.
sys.path.insert(0, str(PROJECT_ROOT / "apps" / "server" / "tests"))

from blog_support import DeterministicBlogSubmitter  # noqa: E402
from database_support import migrated_database  # noqa: E402
from zhiyan_support import DeterministicJwtVerifier, RecordingDispatcher  # noqa: E402

from liyan_server.app import create_app  # noqa: E402
from liyan_server.publication.blog import (  # noqa: E402
    BlogOutcomeUnknown,
    BlogPreviewAccepted,
    BlogPreviewSubmission,
)
from liyan_server.settings import Settings  # noqa: E402

#: A title containing this asks the Blog double for 结果未知 instead of a Preview.
#: A browser cannot reach into the double's outcome queue, and the alternative —
#: a second server started in a different mode — would make the suite's hardest
#: journey the one that shares least with the others.
UNKNOWN_OUTCOME_MARKER = "结果未知"

TARGETS = (
    '[{"key":"lsforum","display_name":"LSForum Blog",'
    '"site_url":"https://blog.example.invalid",'
    '"api_base_url":"https://blog.example.invalid",'
    '"emails":["writer@example.com"]}]'
)


class MarkerBlogSubmitter(DeterministicBlogSubmitter):
    """A Blog that answers by what the article is called.

    立言阁's three publication outcomes are all terminal and all look different
    to a user, so the browser suite has to be able to ask for each. The title is
    the only thing a browser controls that reaches this far.

    Everything else — recording each submission, defaulting to a Preview — is
    the double the test suite already uses, inherited rather than rebuilt.
    """

    def submit(self, submission: BlogPreviewSubmission) -> BlogPreviewAccepted:
        if UNKNOWN_OUTCOME_MARKER in submission.title:
            self.submissions.append(submission)
            raise BlogOutcomeUnknown("The e2e title asked for an unconfirmed outcome.")
        return super().submit(submission)


class InlineDispatcher(RecordingDispatcher):
    """Runs each Execution as soon as it is queued, on its own thread.

    Not synchronously: the workbench shows 处理中 and polls, and an Execution
    that finished before the request returned would hide every transition the
    browser suite exists to watch. A thread each is enough here — one browser,
    one writer, a handful of runs.
    """

    def __init__(self, database_url: str) -> None:
        super().__init__(database_url)
        self.blog = MarkerBlogSubmitter()

    def dispatch(self, execution_id: UUID, operation: str) -> None:
        threading.Thread(target=self._run, args=(execution_id,), daemon=True).start()

    def _run(self, execution_id: UUID) -> None:
        self.execution_ids.append(execution_id)
        try:
            self.run_next()
        except Exception as error:  # noqa: BLE001 - a browser test wants the reason, not a trace
            print(f"e2e execution {execution_id} failed: {error!r}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="A disposable 立言阁 for browser tests.")
    parser.add_argument("--port", type=int, default=8099)
    arguments = parser.parse_args()

    workspace = Path(tempfile.mkdtemp(prefix="liyan-e2e-"))
    database_url = migrated_database(workspace)
    settings = Settings(
        database_url=database_url,
        allowed_emails="writer@example.com,second@example.com",
        # 5199 is the port the Playwright config starts Vite on, kept away
        # from 5173 so a browser test and a running dev server cannot collide.
        cors_origins=(
            "http://localhost:5199,http://127.0.0.1:5199,"
            "http://localhost:5173,http://127.0.0.1:5173"
        ),
        publication_targets=TARGETS,
        blog_ingest_token="e2e-ingest-secret",
        # Off: the ceiling is a server rule with its own tests, and a browser
        # suite that trips it would fail for a reason it is not about.
        max_active_executions_per_user=0,
        # Same reasoning, and it took a CI failure to notice it was missing.
        # One signed-in writer creates a task per spec, every run's provider is
        # a double that reports no `usage`, and a run whose cost cannot be
        # measured keeps its whole 预扣 — deliberately, so a blinking meter does
        # not hand out reports for free. So the suite spends the real estimate
        # per task and never gets any of it back, and the signup grant is a
        # budget for one or two tasks rather than a dozen.
        #
        # It was already within a task or two of the ceiling and nothing said
        # so; raising the 知言 estimate to what runs actually cost pushed it
        # over, and nine specs failed at 创建任务 with no visible reason. 额度
        # enforcement has its own tests. This suite is about the workbench.
        signup_grant_credits=1_000_000,
    )
    application = create_app(
        settings,
        jwt_verifier=DeterministicJwtVerifier(),
        execution_dispatcher=InlineDispatcher(database_url),
    )

    print(f"e2e server on http://127.0.0.1:{arguments.port}", file=sys.stderr)
    print("  identity: any bearer token is writer@example.com", file=sys.stderr)
    print("  DeepSeek and Blog: deterministic doubles, no network", file=sys.stderr)
    print(f"  database: {database_url}", file=sys.stderr)
    uvicorn.run(application, host="127.0.0.1", port=arguments.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
