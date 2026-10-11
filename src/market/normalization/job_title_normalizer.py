"""Normalize job-title formatting and remove seniority labels."""

import re
import unicodedata

_SENIORITY_TERMS = {
    "associate",
    "graduate",
    "intern",
    "internship",
    "jr",
    "junior",
    "lead",
    "mid",
    "midlevel",
    "principal",
    "senior",
    "sr",
    "staff",
}


def normalize_job_title(value: object) -> str | None:
    """Return a readable title without common seniority/formatting variation.

    The original title should be retained separately in ``job_title``.
    """
    if not isinstance(value, str):
        return None

    text = unicodedata.normalize("NFKC", value).strip()
    if not text:
        return None
    text = re.sub(r"\b(?:entry[ -]?level|mid[ -]?level)\b", " ", text, flags=re.I)
    text = re.sub(r"[\-/–—|]+", " ", text)
    text = "".join(char if char.isalnum() or char.isspace() else " " for char in text)
    words = [word for word in re.sub(r"\s+", " ", text).split() if word.casefold() not in _SENIORITY_TERMS]

    if words and re.fullmatch(r"(?:\d+|i{1,3}|iv)", words[-1], flags=re.I):
        words.pop()

    return " ".join(words) or None
