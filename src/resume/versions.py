"""Versions that identify output-affecting resume extraction behavior.

Bump a version whenever the corresponding prompt, schema, or deterministic
processing behavior changes. Adding optional profile fields is backward
compatible and does not change the profile contract version.
"""

PROMPT_VERSION = "4"
EXTRACTION_SCHEMA_VERSION = 1
PROFILE_SCHEMA_VERSION = 1
PROCESSING_VERSION = "9"
