import hashlib
import json


def canonical_hash(value: object) -> str:
    """The one identity function for stored content across the server.

    Canonical JSON keeps the digest stable whatever order a caller built the value
    in, and leaving non-ASCII unescaped lets a browser recompute the same digest.
    """
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
