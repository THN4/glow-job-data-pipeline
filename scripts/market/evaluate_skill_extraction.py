"""Run a small, opt-in quality check against the configured Gemini model."""

import argparse
import json
from pathlib import Path

from src.market.skill_extraction.extractor import extract_job_skills


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = PROJECT_ROOT / "tests" / "market" / "fixtures" / "skill_evaluation_cases.json"
REPORT_PATH = PROJECT_ROOT / "data" / "processed" / "skill_evaluation" / "report.json"


def main(case_name: str | None = None) -> int:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if case_name is not None:
        cases = [case for case in cases if case["name"] == case_name]
        if not cases:
            raise ValueError(f"Unknown evaluation case: {case_name}")
    report = []
    for case in cases:
        try:
            skills = extract_job_skills(case["job_title"], case["job_description"])
            actual = {
                (
                    skill["raw_skill_name"].casefold(),
                    skill["requirement_type"],
                    skill["proficiency_level"],
                )
                for skill in skills
            }
            expected = {
                (
                    skill["skill"].casefold(),
                    skill["requirement_type"],
                    skill["proficiency_level"],
                )
                for skill in case["expected"]
            }
            forbidden = {
                skill.casefold() for skill in case["forbidden"]
            }
            passed = expected == actual and not any(
                skill[0] in forbidden for skill in actual
            )
            report.append(
                {"case": case["name"], "passed": passed, "skills": skills}
            )
        except Exception as error:
            report.append(
                {
                    "case": case["name"],
                    "passed": False,
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for result in report:
        print(f"{result['case']}: {'PASS' if result['passed'] else 'REVIEW'}")
    print(f"Report: {REPORT_PATH}")
    return 0 if all(result["passed"] for result in report) else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", help="Run one named JD case only.")
    args = parser.parse_args()
    raise SystemExit(main(args.case))
