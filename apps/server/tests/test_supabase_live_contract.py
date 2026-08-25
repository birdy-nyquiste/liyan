"""The real Supabase JWKS document, fetched once and read the way auth reads it.

`test_jwks_verifier.py` proves the verifier's rules against keys a test made.
That is the right way to test rules, and it cannot tell you the one thing this
can: whether the project you configured actually publishes a document with the
fields those rules require. A Supabase project still signing with a shared
secret has no JWKS at all, and its `keys` array is empty — every sign-in then
fails at the first request with nothing in the logs but `InvalidAccessToken`.

Opt-in, because it reaches the network:

    LIYAN_LIVE_SUPABASE=1 .venv/bin/python -m pytest \\
        apps/server/tests/test_supabase_live_contract.py

It reads a public document and signs nothing in. Pointing it at Production is
harmless — but the answer only means anything for the project whose issuer is
in the environment being released.
"""

import os

import pytest

from liyan_server.auth import HttpJwksLoader
from liyan_server.settings import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("LIYAN_LIVE_SUPABASE") != "1",
    reason="Set LIYAN_LIVE_SUPABASE=1 to run the live Supabase JWKS contract check.",
)

#: The two the verifier accepts. Anything else is a project this build cannot read.
SUPPORTED_ALGORITHMS = {"ES256", "RS256"}


@pytest.fixture
def jwks() -> dict[str, object]:
    settings = Settings()
    assert settings.supabase_issuer, "LIYAN_SUPABASE_ISSUER is empty."
    return HttpJwksLoader(settings.resolved_supabase_jwks_url)()


def test_the_project_publishes_at_least_one_signing_key(jwks: dict[str, object]) -> None:
    """An empty `keys` array is what a legacy HS256 project looks like from here."""
    keys = jwks["keys"]
    assert isinstance(keys, list)
    assert keys, "This Supabase project publishes no JWKS keys; asymmetric JWTs are not enabled."


def test_every_published_key_carries_what_the_verifier_selects_on(
    jwks: dict[str, object],
) -> None:
    """`kid` and `alg` are how one key is chosen for one token, so both must be there."""
    keys = jwks["keys"]
    assert isinstance(keys, list)
    for key in keys:
        assert isinstance(key, dict)
        assert key.get("kid"), key
        assert key.get("alg") in SUPPORTED_ALGORITHMS, key


def test_no_private_material_is_published(jwks: dict[str, object]) -> None:
    """A public JWKS carrying `d` would mean the signing key itself is on the internet."""
    keys = jwks["keys"]
    assert isinstance(keys, list)
    for key in keys:
        assert isinstance(key, dict)
        assert "d" not in key, "The published JWKS contains private key material."
