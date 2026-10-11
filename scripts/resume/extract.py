"""Extract one CV file with the configured model and print the result (no API server needed).

    python -m scripts.resume.extract path/to/cv.pdf              # full JSON
    python -m scripts.resume.extract path/to/cv.pdf --summary    # compact view laid out like the database tables

Uses EXTRACTOR / LLM_* from .env.
"""

import asyncio
import sys
import time
from pathlib import Path

from src.resume.config import ResumeModelSettings
from src.resume.errors import ResumeProcessingError
from src.resume.extraction.providers import create_extractor
from src.resume.normalization.postprocess import BuildContext, build_result
from src.resume.parsing.preprocess import Limits, prepare_cv


async def main(path: str, summary: bool = False) -> int:
    cfg = ResumeModelSettings()
    extractor = create_extractor(cfg)
    data = Path(path).read_bytes()
    try:
        t0 = time.monotonic()
        prepared = await asyncio.to_thread(prepare_cv, data, Limits(cfg.MAX_PDF_PAGES, cfg.MAX_IMAGE_PAGES))
        t1 = time.monotonic()
        print(
            f"Prepared as {prepared.kind} ({prepared.page_count} page(s)) in {(t1 - t0) * 1000:.0f} ms; "
            f"calling {extractor.name}...",
            file=sys.stderr,
        )
        out = await extractor.extract(prepared)
        t2 = time.monotonic()
    except ResumeProcessingError as err:
        print(f"Failed: {err.code}: {err.message}", file=sys.stderr)
        return 2

    result = build_result(
        out.extraction,
        BuildContext(
            extraction_id="cli",
            model=extractor.name,
            duration_ms=round((t2 - t0) * 1000),
            input_kind=prepared.kind,
            page_count=prepared.page_count,
            source_text=prepared.text if prepared.kind == "text" and extractor.groundable else None,
            warnings=list(prepared.warnings),
        ),
    )
    if summary:
        print(db_view(result))
    else:
        print(result.model_dump_json(by_alias=True, indent=2))
    usage = out.usage
    print(
        f"\nModel time {t2 - t1:.1f} s, total {t2 - t0:.1f} s, "
        f"tokens in/out {usage.input_tokens if usage else '?'}/{usage.output_tokens if usage else '?'}, "
        f"isDocumentACv={out.extraction.is_document_a_cv}, needs review: {result.meta.review_count}",
        file=sys.stderr,
    )
    return 0


def db_view(result) -> str:
    """The extraction laid out like the app.* tables (docs/cv-extraction/08, 09). Read-only preview."""
    p, meta, d = result.profile, result.meta, result.profile.derived
    flag = lambda i: " [REVIEW]" if i.needs_review else ""
    out = [f"== app.user_profiles   (model: {meta.model}, input: {meta.input_kind}, review items: {meta.review_count})"]
    out.append(f"   display_name={p.personal.full_name!r}  location={p.personal.location!r}  background_summary={p.summary!r}")
    if d:
        out.append(f"   current_job_title={d.current_job_title!r}  years_experience={d.years_experience}  "
                   f"education_level={d.education_level!r}  field_of_study={d.field_of_study!r}  suggested_status={d.suggested_status!r}")
    out.append("\n== app.user_educations")
    for e in p.education:
        out.append(f"   {e.institution!r} | {e.degree!r} | {e.field_of_study!r} | {e.start_date} -> {e.end_date or ('now' if e.is_current else None)} | {e.confidence}{flag(e)}")
    out.append("\n== app.user_experiences   (work / internship / project)")
    for x in p.experience:
        kind = "internship" if x.employment_type == "internship" else "work"
        out.append(f"   [{kind}] {x.title!r} @ {x.organization!r} | {x.start_date} -> {x.end_date or ('now' if x.is_current else None)} | {x.confidence}{flag(x)}")
    for x in p.projects:
        out.append(f"   [project] {x.name!r} | {x.start_date} -> {x.end_date} | {x.confidence}{flag(x)}")
    for c in p.certifications:
        out.append(f"   [{c.kind}] {c.name!r} | {c.issuer!r} | {c.date} | {c.detail!r}{flag(c)}   (no table yet: see docs 08, D3)")
    out.append("\n== app.user_skills + user_skill_evidence   (name | proficiency_level | basis | evidence)")
    for sk in p.technical_skills:
        ev = ", ".join(e.evidence_type for e in sk.evidence) or "-"
        out.append(f"   {sk.name:<16} {sk.proficiency:<13} {sk.proficiency_basis:<9} {ev}{flag(sk)}")
    out.append("\n== kept only in extracted_json   (no table)")
    out.append(f"   tools={[t.name for t in p.tools]}  soft_skills={[t.name for t in p.soft_skills]}  "
               f"languages={[(l.name, l.proficiency) for l in p.languages]}")
    if meta.warnings:
        out.append(f"   warnings={meta.warnings}")
    return "\n".join(out)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Usage: python -m scripts.resume.extract <cv.pdf|cv.png|cv.jpg> [--summary]", file=sys.stderr)
        sys.exit(1)
    sys.exit(asyncio.run(main(args[0], summary="--summary" in sys.argv)))
