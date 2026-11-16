"""The answer vocabulary shared by ask, grade and score, and the JSON-schema helpers the reply formats are built from.

Two kinds of schema live here:
  * the five answers a criterion can get (YES / NO / N/A / UNCLEAR / NOT_FOUND) and the one rule for which of them
    downstream code may trust (effective_answer);
  * helpers for the JSON schemas sent to the model as the reply format (object(), PAGE) and the checker that every
    reply is held to in code (schema_problems), whatever the provider promised.
"""

YES = "YES"
NO = "NO"
NA = "N/A"
UNCLEAR = "UNCLEAR"
NOT_FOUND = "NOT_FOUND"

ANSWERS = [YES, NO, NA, UNCLEAR, NOT_FOUND]


def hospital_id(value: str) -> str:
    """Normalize a PFI to the hospital_id string. Excel sometimes turns ids into floats ("9876.0")."""
    v = str(value).strip()
    if v.replace(".", "", 1).isdigit() and v.endswith(".0"):
        v = v[:-2]
    return v


def effective_answer(record: dict) -> str:
    """The answer downstream code is allowed to trust.

    A YES/NO is only trusted if code verified its quote against the source text.
    Otherwise it is downgraded to UNCLEAR (manual review). Missing records are UNCLEAR.
    """
    answer = record.get("answer", UNCLEAR)
    if answer in (YES, NO) and record.get("quote_verified") is not True:
        return UNCLEAR
    if answer not in ANSWERS:
        return UNCLEAR
    return answer


# ---------------------------------------------------------------------------------------------------------------
# JSON schemas for the reply formats

# A page number from the [[page N]] markers, or null when the item quotes nothing.
PAGE = {"anyOf": [{"type": "integer"}, {"type": "null"}]}


def object_schema(properties: dict) -> dict:
    """A JSON object with exactly these properties, all required (the shape structured outputs require)."""
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_JSON_TYPES = {"object": dict, "array": list, "string": str, "null": type(None), "boolean": bool}


def schema_problems(value, schema: dict, where: str = "reply", limit: int = 5) -> list[str]:
    """Where a parsed reply breaks the reply format, in words (empty list: it fits). Covers what our formats use:
    type, properties / required / additionalProperties false, items, enum, anyOf.

    The Claude API enforces the format itself. For non-Claude models on Bedrock enforcement depends on the API (through
    Converse, Kimi renamed and dropped fields on long prompts, Nov 12), so every reply is checked in code."""
    out: list[str] = []

    def check(v, s, at):
        if len(out) >= limit:
            return
        if "anyOf" in s:
            if not any(not schema_problems(v, alt, at, 1) for alt in s["anyOf"]):
                out.append(f"{at}: matches none of the allowed shapes")
            return
        t = s.get("type")
        if t == "integer":
            ok = isinstance(v, int) and not isinstance(v, bool)
        elif t == "number":
            ok = isinstance(v, (int, float)) and not isinstance(v, bool)
        else:
            ok = t is None or isinstance(v, _JSON_TYPES[t])
        if not ok:
            out.append(f"{at}: expected {t}, got {type(v).__name__}")
            return
        if "enum" in s and v not in s["enum"]:
            out.append(f"{at}: {str(v)[:40]!r} is not one of {s['enum']}")
        if t == "object":
            props = s.get("properties", {})
            missing = [k for k in s.get("required", []) if k not in v]
            extra = [k for k in v if k not in props] if s.get("additionalProperties") is False else []
            if missing:
                out.append(f"{at}: missing {missing}")
            if extra:
                out.append(f"{at}: unexpected {extra}")
            for k, sub in props.items():
                if k in v:
                    check(v[k], sub, f"{at}.{k}")
        if t == "array" and "items" in s:
            for i, item in enumerate(v):
                check(item, s["items"], f"{at}[{i}]")

    check(value, schema, where)
    return out
