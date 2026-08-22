from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from liyan_server.auth import HttpJwksLoader, InvalidAccessToken, JwksJwtVerifier, VerifiedIdentity

ISSUER = "https://project.supabase.co/auth/v1"
AUDIENCE = "authenticated"


def signing_material() -> tuple[ec.EllipticCurvePrivateKey, dict[str, Any]]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_jwk = ECAlgorithm.to_jwk(private_key.public_key(), as_dict=True)
    public_jwk.update({"kid": "test-key", "alg": "ES256", "use": "sig"})
    return private_key, public_jwk


def token_for(
    private_key: ec.EllipticCurvePrivateKey,
    **claim_overrides: object,
) -> str:
    now = datetime.now(UTC)
    claims: dict[str, object] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "supabase-user-1",
        "email": "writer@example.com",
        "role": "authenticated",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    claims.update(claim_overrides)
    return jwt.encode(claims, private_key, algorithm="ES256", headers={"kid": "test-key"})


def test_verifies_a_supabase_identity_with_the_matching_jwks_key() -> None:
    private_key, public_jwk = signing_material()
    verifier = JwksJwtVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        load_jwks=lambda: {"keys": [public_jwk]},
    )

    identity = verifier.verify(token_for(private_key))

    assert identity == VerifiedIdentity(
        subject="supabase-user-1",
        email="writer@example.com",
    )


@pytest.mark.parametrize(
    "claim_overrides",
    [
        {"iss": "https://attacker.example/auth/v1"},
        {"aud": "another-service"},
        {"exp": datetime.now(UTC) - timedelta(seconds=1)},
    ],
    ids=["wrong-issuer", "wrong-audience", "expired"],
)
def test_rejects_tokens_with_invalid_required_claims(claim_overrides: dict[str, object]) -> None:
    private_key, public_jwk = signing_material()
    verifier = JwksJwtVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        load_jwks=lambda: {"keys": [public_jwk]},
    )

    with pytest.raises(InvalidAccessToken):
        verifier.verify(token_for(private_key, **claim_overrides))


def test_rejects_a_token_signed_by_a_key_not_in_the_jwks() -> None:
    trusted_private_key, trusted_public_jwk = signing_material()
    untrusted_private_key, _ = signing_material()
    verifier = JwksJwtVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        load_jwks=lambda: {"keys": [trusted_public_jwk]},
    )

    with pytest.raises(InvalidAccessToken):
        verifier.verify(token_for(untrusted_private_key))


def test_rejects_a_token_that_does_not_have_the_authenticated_role() -> None:
    private_key, public_jwk = signing_material()
    verifier = JwksJwtVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        load_jwks=lambda: {"keys": [public_jwk]},
    )

    with pytest.raises(InvalidAccessToken):
        verifier.verify(token_for(private_key, role="anon"))


def test_loads_and_caches_the_supabase_jwks_discovery_document() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"keys": [{"kid": "key-1"}]})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    loader = HttpJwksLoader(
        "https://project.supabase.co/auth/v1/.well-known/jwks.json",
        client=client,
    )

    first = loader()
    second = loader()

    assert first == {"keys": [{"kid": "key-1"}]}
    assert second == first
    assert [str(request.url) for request in requests] == [
        "https://project.supabase.co/auth/v1/.well-known/jwks.json"
    ]
