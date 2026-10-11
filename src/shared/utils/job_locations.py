"""Small helpers for interpreting explicit country markers in job locations."""

import re


def country_code_from_location(value: object) -> str | None:
    """Infer Thailand only when the location contains an explicit country marker."""
    if not isinstance(value, str):
        return None

    location = value.casefold()
    if "thailand" in location or "ประเทศไทย" in location:
        return "TH"
    if re.search(r"(?:^|[\s,])th(?=$|[\s,])", location):
        return "TH"
    return None
