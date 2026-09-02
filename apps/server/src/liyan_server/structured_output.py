"""One provider-facing JSON Schema, derived from a typed document.

知言 and 主题知言 both ask a provider for structured output, and both derive the
schema they send from the Pydantic document they will validate against — which
is the only way the provider's contract and the workbench's renderer cannot
drift apart. The two rules for turning one into the other are the provider's,
not the domain's, so they live here rather than in either report module.
"""

from pydantic import BaseModel

#: Keywords that only tighten a string. Strict structured output rejects them,
#: so they are dropped from what is sent; application acceptance is what
#: actually enforces them.
GENERATION_ONLY_KEYWORDS = frozenset({"minLength", "maxLength", "pattern", "format"})


def provider_json_schema(document: type[BaseModel]) -> dict[str, object]:
    """The schema for `document` as strict structured output accepts it.

    Strict mode requires every object to close itself and list all of its keys
    as required, which is stated explicitly rather than inferred from the
    model's `extra` policy.
    """
    return _closed_objects(_without_generation_only_keywords(document.model_json_schema()))


def _closed_objects(schema: dict[str, object]) -> dict[str, object]:
    properties = schema.get("properties")
    if isinstance(properties, dict):
        schema["additionalProperties"] = False
        schema["required"] = list(properties)
    for value in schema.values():
        if isinstance(value, dict):
            _closed_objects(value)
        elif isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict):
                    _closed_objects(entry)
    return schema


def _without_generation_only_keywords(schema: object) -> dict[str, object]:
    if not isinstance(schema, dict):
        raise TypeError("A JSON Schema fragment must be an object.")
    cleaned: dict[str, object] = {}
    for key, value in schema.items():
        if key in GENERATION_ONLY_KEYWORDS:
            continue
        if isinstance(value, dict):
            cleaned[key] = _without_generation_only_keywords(value)
        elif isinstance(value, list):
            cleaned[key] = [
                _without_generation_only_keywords(entry) if isinstance(entry, dict) else entry
                for entry in value
            ]
        else:
            cleaned[key] = value
    return cleaned
