"""Turns raw model output into a CvProfile. All functions here are pure.

The API and storage layers consume the result built here.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable
from urllib.parse import urlparse

from .derive import derive_profile, explicit_level_from_text, infer_level, is_certified, skill_usage, snippet_with_skill
from ..schemas.cv_extraction import (
    Certification,
    Confidence,
    CvExtraction,
    CvExtractionMeta,
    CvExtractionResult,
    CvProfile,
    Education,
    Experience,
    InputKind,
    Language,
    NamedItem,
    Personal,
    Project,
    SkillEvidence,
    TechnicalSkill,
)
from .skill_aliases import normalize_skill_name, skill_spellings

_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}
_DATE_RE = re.compile(r"^(\d{4})(?:-(0[1-9]|1[0-2]))?$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_MIN_YEAR = 1950
_BE_OFFSET = 543  # Buddhist Era -> Common Era
_BE_MIN, _BE_MAX = 2450, 2650


@dataclass
class BuildContext:
    extraction_id: str
    model: str
    duration_ms: int
    input_kind: InputKind
    page_count: int | None
    #: Extracted CV text for the grounding check. None for image inputs or the mock.
    source_text: str | None = None
    warnings: list[str] = field(default_factory=list)
    #: Injected for deterministic tests (duration of ongoing jobs, inferred skill levels). Defaults to today.
    today: date | None = None


def build_result(ex: CvExtraction, ctx: BuildContext) -> CvExtractionResult:
    warnings = [*ctx.warnings, *ex.warnings]
    ground = make_grounder(ctx.source_text) if ctx.source_text else None

    def grounded(conf: Confidence, *needles: str | None) -> Confidence:
        """Downgrades confidence to 'low' when a key string is missing from the CV text."""
        if ground and any(n and not ground(n) for n in needles):
            return "low"
        return conf

    # --- personal ---------------------------------------------------------------------
    email = _valid_email(ex.personal.email, warnings)
    links = []
    for link in ex.personal.links:
        url = _with_scheme(link.url)
        if _valid_url(url):
            links.append({"label": link.label, "url": url})
        else:
            warnings.append(f'Ignored an invalid link: "{link.url}".')
    p_conf = grounded(ex.personal.confidence, ex.personal.full_name)
    personal = Personal(
        **{
            **ex.personal.model_dump(),
            "email": email,
            "links": links,
            "confidence": p_conf,
            "needs_review": p_conf != "high",
            "source": "cv",
        }
    )

    # --- education --------------------------------------------------------------------
    education = []
    for e in ex.education:
        dates, d_conf = fix_range(e.start_date, e.end_date, e.is_current)
        conf = _min(grounded(e.confidence, e.institution), d_conf)
        education.append(
            _with_meta(Education, "edu", {**e.model_dump(), **dates, "confidence": conf}, e.institution is None)
        )

    soft_skills = [
        _with_meta(NamedItem, "soft", {**d, "confidence": grounded(d["confidence"], d["name"])})
        for d in _dedupe_by_name(ex.soft_skills)
    ]

    # --- experience -------------------------------------------------------------------
    experience = []
    for x in ex.experience:
        dates, d_conf = fix_range(x.start_date, x.end_date, x.is_current)
        conf = _min(grounded(x.confidence, x.organization, x.title), d_conf)
        experience.append(
            _with_meta(
                Experience,
                "exp",
                {**x.model_dump(), **dates, "technologies": _normalize_list(x.technologies), "confidence": conf},
                x.title is None or x.organization is None,
            )
        )

    # --- projects ---------------------------------------------------------------------
    projects = []
    for pr in ex.projects:
        dates, d_conf = fix_range(pr.start_date, pr.end_date, False)
        url = None
        if pr.url:
            candidate = _with_scheme(pr.url)
            if _valid_url(candidate):
                url = candidate
            else:
                warnings.append(f'Ignored an invalid project URL: "{pr.url}".')
        conf = _min(grounded(pr.confidence, pr.name), d_conf)
        projects.append(
            _with_meta(
                Project,
                "prj",
                {
                    **pr.model_dump(),
                    "start_date": dates["start_date"],
                    "end_date": dates["end_date"],
                    "url": url,
                    "technologies": _normalize_list(pr.technologies),
                    "confidence": conf,
                },
                pr.name is None,
            )
        )

    # --- certifications, tools, languages ---------------------------------------------
    certifications = []
    for c in ex.certifications:
        cert_date = valid_date(c.date)
        date_ok = _date_ok(c.date, cert_date)
        conf = _min(grounded(c.confidence, c.name), "high" if date_ok else "low")
        certifications.append(
            _with_meta(Certification, "cert", {**c.model_dump(), "date": cert_date, "confidence": conf}, c.name is None)
        )
    tools = [
        _with_meta(NamedItem, "tool", {**t, "confidence": grounded(t["confidence"], t["name"])})
        for t in _dedupe_by_name(ex.tools)
    ]
    languages = [
        _with_meta(Language, "lang", {**d, "confidence": grounded(d["confidence"], d["name"])})
        for d in _dedupe_by_name(ex.languages)
    ]

    # --- skills: normalized, deduplicated, with proficiency + evidence -------------------
    today = ctx.today or date.today()
    skill_map: dict[str, dict] = {}
    for sk in ex.technical_skills:
        name = normalize_skill_name(sk.name)
        if not name:
            continue
        conf: Confidence = sk.confidence
        if ground and not any(ground(sp) for sp in skill_spellings(sk.name)):
            conf = "low"
        prev = skill_map.get(name.lower())
        if prev is None or _RANK[conf] > _RANK[prev["confidence"]]:
            skill_map[name.lower()] = {**sk.model_dump(), "name": name, "confidence": conf}
        elif sk.proficiency != "unknown" and prev["proficiency"] == "unknown":
            prev["proficiency"] = sk.proficiency

    technical_skills = []
    for d in skill_map.values():
        technical_skills.append(
            _with_meta(TechnicalSkill, "sk", _enrich_skill(d, ctx.source_text, experience, projects, certifications, today))
        )

    profile = CvProfile(
        personal=personal,
        summary=ex.summary,
        education=education,
        technical_skills=technical_skills,
        soft_skills=soft_skills,
        experience=experience,
        projects=projects,
        certifications=certifications,
        tools=tools,
        languages=languages,
    )
    profile = profile.model_copy(update={"derived": derive_profile(profile, today)})
    return CvExtractionResult(
        profile=profile,
        meta=CvExtractionMeta(
            extraction_id=ctx.extraction_id,
            model=ctx.model,
            duration_ms=ctx.duration_ms,
            input_kind=ctx.input_kind,
            cached=False,
            detected_language=ex.detected_language,
            page_count=ctx.page_count,
            warnings=list(dict.fromkeys(warnings)),
            review_count=count_review(profile),
        ),
    )


def confirm_profile(profile: CvProfile, today: date | None = None) -> CvProfile:
    """For PUT /profiles: the user has confirmed everything. Derived facts are recomputed from the edited data."""

    def done(items):
        return [i.model_copy(update={"needs_review": False}) for i in items]

    confirmed = profile.model_copy(
        update={
            "personal": profile.personal.model_copy(update={"needs_review": False}),
            "education": done(profile.education),
            "technical_skills": done(profile.technical_skills),
            "soft_skills": done(profile.soft_skills),
            "experience": done(profile.experience),
            "projects": done(profile.projects),
            "certifications": done(profile.certifications),
            "tools": done(profile.tools),
            "languages": done(profile.languages),
        }
    )
    return confirmed.model_copy(update={"derived": derive_profile(confirmed, today or date.today())})


def count_review(p: CvProfile) -> int:
    lists = [
        p.education,
        p.technical_skills,
        p.soft_skills,
        p.experience,
        p.projects,
        p.certifications,
        p.tools,
        p.languages,
    ]
    return (1 if p.personal.needs_review else 0) + sum(1 for lst in lists for i in lst if i.needs_review)


# ------------------------------------------------------------------------------ helpers


def _enrich_skill(
    d: dict,
    source_text: str | None,
    experiences: list[Experience],
    projects: list[Project],
    certifications: list[Certification],
    today: date,
) -> dict:
    """Adds proficiency (explicit or inferred), its basis and evidence to one extracted skill (as a dict)."""
    name = d["name"]
    if source_text:
        # With the CV text available, the code decides what the CV states: a level the model claims
        # but the text doesn't show is dropped (hallucination guard).
        explicit = explicit_level_from_text(source_text, name)
    else:
        explicit = d["proficiency"]  # images / mock: only the model can read the level

    months, evidence = skill_usage(name, experiences, projects, today)
    if source_text:
        quote = snippet_with_skill(source_text, name)
        if quote and not evidence:
            evidence.append(SkillEvidence(evidence_type="resume_text", text=quote))
    if explicit != "unknown":
        level, basis = explicit, "explicit"
    else:
        level = infer_level(months, is_certified(name, certifications))
        basis = "inferred" if level != "unknown" else "unknown"
    return {**d, "proficiency": level, "proficiency_basis": basis, "evidence": evidence}


def _with_meta(model, prefix: str, data: dict, missing_key_field: bool = False):
    return model(
        **data,
        id=f"{prefix}_{uuid.uuid4().hex[:8]}",
        needs_review=data["confidence"] != "high" or missing_key_field,
        source="cv",
    )


def _min(a: Confidence, b: Confidence) -> Confidence:
    return a if _RANK[a] <= _RANK[b] else b


_MONTHS: dict[str, int] = {}
for _i, _names in enumerate(
    [
        ["jan", "january", "มกราคม", "มค"],
        ["feb", "february", "กุมภาพันธ์", "กพ"],
        ["mar", "march", "มีนาคม", "มีค"],
        ["apr", "april", "เมษายน", "เมย"],
        ["may", "พฤษภาคม", "พค"],
        ["jun", "june", "มิถุนายน", "มิย"],
        ["jul", "july", "กรกฎาคม", "กค"],
        ["aug", "august", "สิงหาคม", "สค"],
        ["sep", "sept", "september", "กันยายน", "กย"],
        ["oct", "october", "ตุลาคม", "ตค"],
        ["nov", "november", "พฤศจิกายน", "พย"],
        ["dec", "december", "ธันวาคม", "ธค"],
    ],
    start=1,
):
    for _n in _names:
        _MONTHS[_n] = _i


def normalize_date_format(value: str | None) -> str | None:
    """Loose date formats -> 'YYYY' / 'YYYY-MM'. No range check. Returns None if the format is not understood.

    Handles 'Jun 2023', 'June 2023', '2023 June', '06/2023', '2023/06', '2023-6', and Thai month names.
    Models sometimes ignore the requested format, so the backend accepts what is unambiguous.
    """
    if not value or not value.strip():
        return None
    v = value.strip().lower().replace(".", "")
    if m := re.fullmatch(r"(\d{4})", v):
        return m.group(1)
    if m := re.fullmatch(r"(\d{4})\s*[-/]\s*(\d{1,2})", v):
        year, month = m.group(1), int(m.group(2))
    elif m := re.fullmatch(r"(\d{1,2})\s*[-/]\s*(\d{4})", v):
        year, month = m.group(2), int(m.group(1))
    elif m := re.fullmatch(r"([^\d\s/\-]+)\s*,?\s*(\d{4})", v):
        year, month = m.group(2), _MONTHS.get(m.group(1), 0)
    elif m := re.fullmatch(r"(\d{4})\s+([^\d\s/\-]+)", v):
        year, month = m.group(1), _MONTHS.get(m.group(2), 0)
    else:
        return None
    return f"{year}-{month:02d}" if 1 <= month <= 12 else None


def valid_date(value: str | None) -> str | None:
    """Returns the date as 'YYYY'/'YYYY-MM' with a plausible year, else None.

    Loose formats are normalized first (see ``normalize_date_format``).
    Thai CVs often use the Buddhist Era (2563 = 2020 CE). A year that is impossible as a CE year but
    plausible as a BE year is converted (minus 543). The result then differs from the normalized input,
    so ``fix_range`` lowers the confidence and the item is flagged for the user to confirm.
    """
    v = normalize_date_format(value)
    if v is None:
        return None
    m = _DATE_RE.match(v)
    if not m:
        return None
    year, month = int(m.group(1)), m.group(2)
    if year > datetime.now().year + 1 and _BE_MIN <= year <= _BE_MAX:
        year -= _BE_OFFSET
        v = f"{year}-{month}" if month else str(year)
    return v if _MIN_YEAR <= year <= datetime.now().year + 1 else None


def _date_ok(original: str | None, result: str | None) -> bool:
    """True when nothing was stated, or the date only needed reformatting (not converting or discarding)."""
    if not original or not original.strip():
        return True
    return result is not None and result == normalize_date_format(original)


def fix_range(start: str | None, end: str | None, is_current: bool) -> tuple[dict, Confidence]:
    """Validates a start/end range; any problem lowers confidence. Ongoing items never have an end date."""
    s = valid_date(start)
    e = None if is_current else valid_date(end)
    ok = _date_ok(start, s) and (is_current or _date_ok(end, e))
    if s and e and s[:7] > e[:7]:
        ok = False
    return {"start_date": s, "end_date": e, "is_current": is_current}, ("high" if ok else "low")


def _normalize_list(names: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for n in names:
        name = normalize_skill_name(n)
        if name and name.lower() not in seen:
            seen[name.lower()] = name
    return list(seen.values())


def _dedupe_by_name(items) -> list[dict]:
    out: dict[str, dict] = {}
    for i in items:
        name = i.name.strip()
        if not name:
            continue
        prev = out.get(name.lower())
        if prev is None or _RANK[i.confidence] > _RANK[prev["confidence"]]:
            out[name.lower()] = {**i.model_dump(), "name": name}
    return list(out.values())


def _valid_email(value: str | None, warnings: list[str]) -> str | None:
    if not value:
        return None
    v = value.strip()
    if _EMAIL_RE.match(v):
        return v
    warnings.append(f'Ignored an invalid email: "{value}".')
    return None


def _with_scheme(url: str) -> str:
    u = url.strip()
    return u if re.match(r"^https?://", u, re.I) else f"https://{u}"


def _valid_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except ValueError:
        return False
    return p.scheme in ("http", "https") and bool(p.hostname) and " " not in url and "." in (p.hostname or "")


def _norm(s: str) -> str:
    """Normalizes text for matching: NFKC, lowercase, single spaces."""
    return " ".join(unicodedata.normalize("NFKC", s).lower().split())


def _tokens(s: str) -> list[str]:
    out, cur = [], []
    for ch in _norm(s):
        if ch.isalnum() or unicodedata.category(ch).startswith("M") or ch in "+#.":
            cur.append(ch)
        elif cur:
            out.append("".join(cur))
            cur = []
    if cur:
        out.append("".join(cur))
    return out


_COMPACT_STRIP = re.compile(r"[\s\-_.,]")


def make_grounder(source_text: str) -> Callable[[str], bool]:
    """Builds a check 'does this value appear in the CV text?'.

    Short needles (<= 3 chars, e.g. "Go", "C#") must match a whole token; longer ones match as a
    substring, or by >= 80 % token overlap (tolerates reordering / punctuation).
    """
    hay = _norm(source_text)
    hay_compact = _COMPACT_STRIP.sub("", hay)
    hay_tokens = set(_tokens(source_text))

    def ground(needle: str) -> bool:
        n = _norm(needle)
        if not n:
            return True
        if len(n) <= 3:
            return n in hay_tokens
        if n in hay or _COMPACT_STRIP.sub("", n) in hay_compact:
            return True
        toks = _tokens(needle)
        if not toks:
            return True
        found = sum(1 for t in toks if t in hay_tokens or (len(t) > 3 and t in hay))
        return found / len(toks) >= 0.8

    return ground
