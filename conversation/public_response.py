import re

_THOUGHT_BLOCK = re.compile(
    r"\[THOUGHT[^\]]*\].*?(?=\[(?:THOUGHT|REPLY|STATE)[^\]]*\]|\Z)",
    re.DOTALL,
)
_PUBLIC_MARKER = re.compile(r"\[(?:REPLY|STATE)[^\]]*\](?:\[[^\]]+\])?\s*")


def sanitize_public_response(value: str) -> str:
    """Remove private reasoning markers before persistence or transport."""
    without_thoughts = _THOUGHT_BLOCK.sub("", value)
    return _PUBLIC_MARKER.sub("", without_thoughts).strip()
