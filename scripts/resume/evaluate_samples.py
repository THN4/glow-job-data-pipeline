"""Run the fictional resume gold set through Gemini and report expected-field recall.

From the data-pipeline repository root:

    python -m scripts.resume.evaluate_samples --dry-run
    python -m scripts.resume.evaluate_samples --run-model

This is a model-quality evaluation, not a unit-test command. It makes one Gemini
request per selected sample (and may make a repair request), so model execution
requires the explicit ``--run-model`` flag.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.resume.config import ResumeModelSettings
from src.resume.errors import ResumeProcessingError
from src.resume.extraction.providers import create_extractor
from src.resume.normalization.postprocess import BuildContext, build_result
from src.resume.parsing.preprocess import Limits, prepare_cv

PIPELINE_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DIR = PIPELINE_ROOT.parent / "backend" / "test_cvs"
MANIFEST_PATH = SAMPLE_DIR / "manifest.json"
REPORT_DIR = PIPELINE_ROOT / "data" / "processed" / "resume_evaluation"


def _key(value: str | None) -> str:
    """Compare names without making semantic or fuzzy matches."""
    return " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())


def _provider_diagnostic(error: ResumeProcessingError) -> str | None:
    """Keep the SDK's actionable error detail in local eval reports, never credentials."""
    cause = error.__cause__
    if cause is None:
        return None
    detail = f"{type(cause).__name__}: {cause}"
    detail = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED_API_KEY]", detail)
    detail = re.sub(r"(?i)(key=)[^&\s]+", r"\1[REDACTED]", detail)
    return detail[:2000]


def _list_recall(expected: list[str], actual: list[str]) -> dict[str, Any]:
    actual_by_key = {_key(value): value for value in actual if value}
    matched = [value for value in expected if _key(value) in actual_by_key]
    missing = [value for value in expected if _key(value) not in actual_by_key]
    return {
        "expected": len(expected),
        "matched": len(matched),
        "recall": round(len(matched) / len(expected), 4) if expected else None,
        "missing": missing,
        "actual": actual,
    }


def _evaluate_expected(expect: dict[str, Any], result) -> dict[str, Any]:
    profile = result.profile
    actual_skills = [skill.name for skill in profile.technical_skills]
    actual_skills.extend(tool.name for tool in profile.tools)
    metrics: dict[str, Any] = {
        "fullName": {
            "expected": 1,
            "matched": int(_key(expect["fullName"]) == _key(profile.personal.full_name)),
            "recall": float(_key(expect["fullName"]) == _key(profile.personal.full_name)),
            "expectedValue": expect["fullName"],
            "actual": profile.personal.full_name,
            "match": _key(expect["fullName"]) == _key(profile.personal.full_name),
        }
        if expect.get("fullName") is not None
        else None,
        "institutions": _list_recall(
            expect.get("institutions", []),
            [item.institution for item in profile.education if item.institution],
        ),
        "organizations": _list_recall(
            expect.get("organizations", []),
            [item.organization for item in profile.experience if item.organization],
        ),
        "skills": _list_recall(expect.get("skills", []), actual_skills),
        "projects": _list_recall(
            expect.get("projects", []),
            [item.name for item in profile.projects if item.name],
        ),
    }
    expected_levels = expect.get("skillLevels", {})
    if expected_levels:
        actual_levels = {_key(skill.name): skill.proficiency for skill in profile.technical_skills}
        metrics["skillLevels"] = {
            "expected": len(expected_levels),
            "matched": sum(
                actual_levels.get(_key(name)) == level for name, level in expected_levels.items()
            ),
            "details": {
                name: {"expected": level, "actual": actual_levels.get(_key(name))}
                for name, level in expected_levels.items()
            },
        }
    if "organizations" in expect and not expect["organizations"]:
        metrics["noOrganizationsExpected"] = {"pass": not profile.experience}
    if "projects" in expect and not expect["projects"]:
        metrics["noProjectsExpected"] = {"pass": not profile.projects}
    return metrics


def _review_items(profile) -> list[dict[str, Any]]:
    reviewed = []
    if profile.personal.needs_review:
        reviewed.append(
            {"section": "personal", "label": profile.personal.full_name, "confidence": profile.personal.confidence}
        )
    sections = (
        ("technicalSkills", profile.technical_skills),
        ("softSkills", profile.soft_skills),
        ("tools", profile.tools),
        ("languages", profile.languages),
        ("education", profile.education),
        ("experience", profile.experience),
        ("projects", profile.projects),
        ("certifications", profile.certifications),
    )
    for section, items in sections:
        for item in items:
            if not item.needs_review:
                continue
            label = next(
                (getattr(item, key, None) for key in ("name", "institution", "title") if getattr(item, key, None)),
                None,
            )
            reviewed.append({"section": section, "label": label, "confidence": item.confidence})
    return reviewed


async def _run_case(case: dict[str, Any], cfg: ResumeModelSettings, extractor) -> dict[str, Any]:
    case_path = SAMPLE_DIR / case["file"]
    started = time.monotonic()
    base: dict[str, Any] = {"file": case["file"], "expected": case.get("expect", {})}
    try:
        data = case_path.read_bytes()
        prepared = await asyncio.to_thread(
            prepare_cv, data, Limits(cfg.MAX_PDF_PAGES, cfg.MAX_IMAGE_PAGES)
        )
        output = await extractor.extract(prepared)
    except ResumeProcessingError as exc:
        duration_ms = round((time.monotonic() - started) * 1000)
        expected_error = case.get("expect", {}).get("error")
        return {
            **base,
            "status": "error",
            "expectedError": expected_error,
            "errorCode": exc.code,
            "errorMessage": exc.message,
            "providerDiagnostic": _provider_diagnostic(exc),
            "errorMatch": expected_error == exc.code if expected_error else False,
            "durationMs": duration_ms,
        }
    except OSError as exc:
        return {**base, "status": "error", "errorCode": "FILE_READ_ERROR", "errorMessage": str(exc)}

    elapsed_ms = round((time.monotonic() - started) * 1000)
    extraction = output.extraction
    usage = output.usage
    if not extraction.is_document_a_cv:
        expected_error = case.get("expect", {}).get("error")
        return {
            **base,
            "status": "not_a_cv",
            "errorCode": "NOT_A_CV",
            "errorMatch": expected_error == "NOT_A_CV",
            "provider": extractor.provider,
            "model": extractor.name,
            "inputKind": prepared.kind,
            "durationMs": elapsed_ms,
            "tokenUsage": {
                "input": usage.input_tokens if usage else None,
                "output": usage.output_tokens if usage else None,
            },
        }

    result = build_result(
        extraction,
        BuildContext(
            extraction_id=f"eval-{case_path.stem}",
            model=extractor.name,
            duration_ms=elapsed_ms,
            input_kind=prepared.kind,
            page_count=prepared.page_count,
            is_partial=bool(prepared.omitted_pages),
            source_text=prepared.text if prepared.kind == "text" and extractor.groundable else None,
            skill_level_text=(
                prepared.text
                if prepared.kind in ("text", "mixed") and extractor.groundable
                else None
            ),
            warnings=list(prepared.warnings),
            provider=getattr(extractor, "provider", extractor.__class__.__name__),
        ),
    )
    return {
        **base,
        "status": "completed",
        "provider": result.meta.provider,
        "model": result.meta.model,
        "promptVersion": result.meta.prompt_version,
        "extractionSchemaVersion": result.meta.extraction_schema_version,
        "processingVersion": result.meta.processing_version,
        "inputKind": prepared.kind,
        "isPartial": result.meta.is_partial,
        "reviewCount": result.meta.review_count,
        "warnings": result.meta.warnings,
        "durationMs": elapsed_ms,
        "tokenUsage": {
            "input": usage.input_tokens if usage else None,
            "output": usage.output_tokens if usage else None,
        },
        "metrics": _evaluate_expected(case.get("expect", {}), result),
        "actual": {
            "fullName": result.profile.personal.full_name,
            "institutions": [item.institution for item in result.profile.education if item.institution],
            "organizations": [item.organization for item in result.profile.experience if item.organization],
            "skills": [item.name for item in result.profile.technical_skills]
            + [item.name for item in result.profile.tools],
            "projects": [item.name for item in result.profile.projects if item.name],
        },
        "reviewItems": _review_items(result.profile),
    }


def _summarize(cases: list[dict[str, Any]]) -> dict[str, Any]:
    totals: dict[str, dict[str, int]] = {}
    for case in cases:
        for field, metric in case.get("metrics", {}).items():
            if not isinstance(metric, dict) or "expected" not in metric or "matched" not in metric:
                continue
            total = totals.setdefault(field, {"expected": 0, "matched": 0})
            total["expected"] += metric["expected"]
            total["matched"] += metric["matched"]
    recalls = {
        field: {
            **counts,
            "recall": round(counts["matched"] / counts["expected"], 4)
            if counts["expected"]
            else None,
        }
        for field, counts in totals.items()
    }
    return {
        "cases": len(cases),
        "completed": sum(case["status"] == "completed" for case in cases),
        "notACv": sum(case["status"] == "not_a_cv" for case in cases),
        "errors": sum(case["status"] == "error" for case in cases),
        "outcomeMismatches": sum(
            1
            for case in cases
            if case.get("errorMatch") is False
            or (
                case.get("expected", {}).get("error") is not None
                and case["status"] != "not_a_cv"
            )
        ),
        "expectedFieldRecall": recalls,
        "note": "Recall covers expected manifest facts only; it is not precision or a release approval.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="validate sample files and list cases without model calls")
    parser.add_argument("--run-model", action="store_true", help="explicitly run the selected cases through Gemini")
    parser.add_argument("--case", action="append", dest="case_files", help="limit to a manifest filename; repeatable")
    parser.add_argument("--output", type=Path, help="write the JSON report to this path")
    args = parser.parse_args()

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        parser.error(f"Cannot read sample manifest {MANIFEST_PATH}: {exc}")
    cases = [case for case in manifest if not args.case_files or case["file"] in args.case_files]
    unknown = set(args.case_files or []) - {case["file"] for case in manifest}
    if unknown:
        parser.error(f"Unknown sample case(s): {', '.join(sorted(unknown))}")
    missing = [case["file"] for case in cases if not (SAMPLE_DIR / case["file"]).is_file()]
    if missing:
        parser.error(f"Sample file(s) missing from {SAMPLE_DIR}: {', '.join(missing)}")

    if args.dry_run:
        print(json.dumps({"sampleCount": len(cases), "files": [case["file"] for case in cases]}, indent=2))
        return 0
    if not args.run_model:
        parser.error("Model requests are disabled unless you pass --run-model")

    cfg = ResumeModelSettings()
    if cfg.RESUME_EXTRACTOR != "gemini":
        parser.error("Set RESUME_EXTRACTOR=gemini to run a Gemini quality evaluation")
    try:
        extractor = create_extractor(cfg)
        report_cases = asyncio.run(_evaluate_all(cases, cfg, extractor))
    except (ValueError, ResumeProcessingError) as exc:
        parser.error(str(exc))

    now = datetime.now(timezone.utc)
    report = {
        "evaluationVersion": 1,
        "createdAt": now.isoformat(),
        "goldSet": str(MANIFEST_PATH.relative_to(PIPELINE_ROOT.parent)).replace("\\", "/"),
        "provider": extractor.provider,
        "model": extractor.name,
        "summary": _summarize(report_cases),
        "results": report_cases,
    }
    output_path = args.output or REPORT_DIR / f"gemini-{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report written to {output_path}")
    return 0 if report["summary"]["errors"] == 0 and report["summary"]["outcomeMismatches"] == 0 else 2


async def _evaluate_all(cases: list[dict[str, Any]], cfg: ResumeModelSettings, extractor) -> list[dict[str, Any]]:
    results = []
    for index, case in enumerate(cases, start=1):
        print(f"[{index}/{len(cases)}] {case['file']}", file=sys.stderr)
        results.append(await _run_case(case, cfg, extractor))
    return results


if __name__ == "__main__":
    raise SystemExit(main())
