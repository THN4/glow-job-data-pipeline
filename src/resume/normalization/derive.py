"""Facts the database needs that are computed in code, not asked from the model.

Everything here is pure (no I/O) and takes ``today``
as a parameter, so it is deterministic in tests.

  * skill evidence: where the CV shows the skill in use;
  * profile facts: years of experience, current job title, education level, suggested status.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from ..schemas.cv_extraction import (
    CvProfile,
    Derived,
    Education,
    EducationLevel,
    Experience,
    Project,
    Proficiency,
    SkillEvidence,
    SuggestedStatus,
)
from .skill_aliases import skill_spellings

MAX_EVIDENCE = 3

# --------------------------------------------------------------------------- skill evidence


def _month_index(value: str, is_end: bool) -> int | None:
    """'2023-06' -> 2023*12+6. A bare year counts as mid-year (June) on both sides, so 2020-2024 = 48 months."""
    m = re.match(r"^(\d{4})(?:-(\d{2}))?$", value or "")
    if not m:
        return None
    return int(m.group(1)) * 12 + (int(m.group(2)) if m.group(2) else 6)


def interval(start: str | None, end: str | None, is_current: bool, today: date) -> tuple[int, int] | None:
    """(start_month, end_month) of an item, or None when it has no usable start. Ongoing items end today."""
    if not start:
        return None
    s = _month_index(start, False)
    e = today.year * 12 + today.month if is_current or not end else _month_index(end, True)
    if s is None or e is None:
        return None
    return (s, max(e, s + 1))  # at least one month


def union_months(intervals: list[tuple[int, int]]) -> int:
    """Total months covered by the intervals, counting overlaps once."""
    total, cur_end = 0, None
    for s, e in sorted(intervals):
        if cur_end is None or s > cur_end:
            total += e - s
            cur_end = e
        elif e > cur_end:
            total += e - cur_end
            cur_end = e
    return total


# --------------------------------------------------------------------------- finding a skill in text


def _spelling_pattern(spellings: list[str]) -> re.Pattern[str]:
    # not preceded/followed by a word character, so "Go" doesn't match "Google" and "C" doesn't match "CSS"
    alts = "|".join(re.escape(s) for s in sorted(spellings, key=len, reverse=True))
    return re.compile(rf"(?<![\w+#.])(?:{alts})(?![\w+#])", re.IGNORECASE)


_SEGMENT_SPLIT = re.compile(r"[,;|\n•·]+")

# keyword -> level. Thai keywords are matched as substrings (Thai has no spaces between words).
_LEVEL_KEYWORDS: dict[Proficiency, list[str]] = {
    "expert": ["expert", "expertise", "mastery", "specialist", "in-depth", "เชี่ยวชาญ", "ผู้เชี่ยวชาญ"],
    "advanced": ["advanced", "proficient", "proficiency", "strong", "extensive", "ชำนาญ", "ระดับสูง", "ขั้นสูง"],
    "intermediate": ["intermediate", "working knowledge", "competent", "moderate", "ระดับกลาง", "ปานกลาง", "ขั้นกลาง"],
    "beginner": ["beginner", "basic", "basics", "novice", "elementary", "familiar", "familiarity", "learning",
                 "entry level", "entry-level", "ขั้นพื้นฐาน", "พื้นฐาน", "เบื้องต้น", "ขั้นต้น"],
}


def explicit_level_from_text(text: str, name: str) -> Proficiency:
    """Level the CV states next to the skill, e.g. "Python (advanced)", "basic SQL". Else 'unknown'.

    Looks only inside the comma/semicolon/line-separated segment that contains the skill, so
    "Python (advanced), SQL (basic)" gives Python=advanced and SQL=beginner.
    """
    pattern = _spelling_pattern(skill_spellings(name))
    for segment in _SEGMENT_SPLIT.split(text):
        if not pattern.search(segment):
            continue
        low = segment.lower()
        best: tuple[int, Proficiency] | None = None
        for level, words in _LEVEL_KEYWORDS.items():
            for w in words:
                pos = low.find(w)
                if pos >= 0 and (best is None or pos < best[0]):
                    best = (pos, level)
        if best:
            return best[1]
    return "unknown"


def _sentences(text: str) -> list[str]:
    parts = re.split(r"\n+|(?<=[.!?])\s+", text)
    return [p.strip(" -•\t") for p in parts if p.strip(" -•\t") and not p.startswith("--- page")]


def snippet_with_skill(text: str, name: str, limit: int = 200) -> str | None:
    """First line/sentence of the CV text that mentions the skill (any spelling)."""
    pattern = _spelling_pattern(skill_spellings(name))
    for sentence in _sentences(text):
        if pattern.search(sentence):
            return sentence[:limit]
    return None


# --------------------------------------------------------------------------- skill evidence


def _mentions(item_text: str | None, pattern: re.Pattern[str]) -> bool:
    return bool(item_text and pattern.search(item_text))


def skill_usage(
    name: str,
    experiences: list[Experience],
    projects: list[Project],
) -> list[SkillEvidence]:
    """Evidence items from experiences/projects that list or mention this skill."""
    spellings = skill_spellings(name)
    pattern = _spelling_pattern(spellings)
    canonical = {s.lower() for s in spellings}
    evidence: list[SkillEvidence] = []

    def uses(technologies: list[str], *texts: str | None) -> bool:
        return any(t.lower() in canonical for t in technologies) or any(_mentions(t, pattern) for t in texts)

    for x in experiences:
        if uses(x.technologies, x.description, *x.highlights):
            if len(evidence) < MAX_EVIDENCE:
                quote = next((h for h in x.highlights if _mentions(h, pattern)), None) or x.description or x.title
                evidence.append(SkillEvidence(evidence_type="experience", item_id=x.id, text=(quote or "")[:200] or None))
    for p in projects:
        if uses(p.technologies, p.description):
            if len(evidence) < MAX_EVIDENCE:
                evidence.append(SkillEvidence(evidence_type="project", item_id=p.id, text=(p.description or p.name or "")[:200] or None))
    return evidence


# --------------------------------------------------------------------------- profile facts

_NORMALIZE_DOTS = re.compile(r"[.\-_/]")


def education_level_of(degree: str | None) -> EducationLevel | None:
    """'B.Sc.' / 'Master of Engineering' / 'วิทยาศาสตรบัณฑิต' -> bachelor / master / ..."""
    if not degree:
        return None
    d = _NORMALIZE_DOTS.sub("", unicodedata.normalize("NFKC", degree).lower())
    # master/doctorate first: "มหาบัณฑิต" (master) contains "บัณฑิต" (bachelor), "Master" ends in "er" etc.
    if re.search(r"\bphd\b|\bdphil\b|doctor|ดุษฎีบัณฑิต|\bdba\b", d):
        return "doctorate"
    if re.search(r"\bm(sc|eng|a|s|ba|phil|ed|tech|fa|arch)\b|\bmaster|มหาบัณฑิต|\bmba\b", d):
        return "master"
    if re.search(r"\bb(sc|eng|a|s|ba|tech|ed|fa|arch|com)\b|\bbachelor|บัณฑิต|ปริญญาตรี", d):
        return "bachelor"
    if re.search(r"associate|\bas\b|\baa\b", d):
        return "associate"
    if re.search(r"diploma|ปวส|ปวช|อนุปริญญา", d):
        return "diploma"
    if re.search(r"high school|secondary|มัธยม|\bged\b", d):
        return "high_school"
    return "other"


_EDU_RANK: dict[str, int] = {"other": 0, "high_school": 1, "diploma": 2, "associate": 3, "bachelor": 4, "master": 5, "doctorate": 6}


def _highest_education(education: list[Education]) -> Education | None:
    best, best_rank = None, -1
    for e in education:
        level = education_level_of(e.degree)
        rank = _EDU_RANK.get(level or "", -1)
        if rank > best_rank:
            best, best_rank = e, rank
    return best


def derive_profile(profile: CvProfile, today: date) -> Derived:
    """years_experience, current_job_title, education_level, field_of_study, suggested_status."""
    jobs = [x for x in profile.experience if x.employment_type != "volunteer"]
    intervals = [iv for x in jobs if (iv := interval(x.start_date, x.end_date, x.is_current, today))]
    months = union_months(intervals)
    years = round(months / 12, 2) if intervals else None

    # current job: an ongoing role (latest start); otherwise the most recently finished one
    def sort_key(x: Experience) -> tuple[int, int]:
        iv = interval(x.start_date, x.end_date, x.is_current, today)
        return (iv[1], iv[0]) if iv else (0, 0)

    ongoing = [x for x in profile.experience if x.is_current]
    pool = ongoing or profile.experience
    current = max(pool, key=sort_key) if pool else None

    top = _highest_education(profile.education)
    studying = any(e.is_current for e in profile.education)
    working = any(x.is_current and x.employment_type not in ("internship", "volunteer") for x in profile.experience)
    status: SuggestedStatus | None = "employed" if working else "student" if studying else None

    return Derived(
        years_experience=years,
        current_job_title=current.title if current else None,
        education_level=education_level_of(top.degree) if top else None,
        field_of_study=top.field_of_study if top else None,
        suggested_status=status,
    )
