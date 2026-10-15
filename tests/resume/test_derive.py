"""Skill proficiency, evidence and derived profile facts (docs/cv-extraction/06-profile-data-requirements.md)."""

from datetime import date

from src.resume.normalization.derive import (
    derive_profile,
    education_level_of,
    explicit_level_from_text,
    interval,
    snippet_with_skill,
    union_months,
)
from src.resume.extraction.providers.mock import mock_extraction
from src.resume.normalization.postprocess import BuildContext, build_result, confirm_profile
from src.resume.schemas.cv_extraction import CvExtraction

TODAY = date(2026, 10, 5)


def ctx(**kw) -> BuildContext:
    base = dict(extraction_id="j", model="t", duration_ms=1, input_kind="text", page_count=1, today=TODAY)
    return BuildContext(**{**base, **kw})


def extraction(**patch) -> CvExtraction:
    data = mock_extraction().model_dump(by_alias=True)
    data.update(patch)
    return CvExtraction.model_validate(data)


def skill(name: str, level: str = "unknown") -> dict:
    return {"name": name, "category": "other", "confidence": "high", "proficiency": level}


def job(title="Dev", org="Acme", start="2020-01", end=None, current=False, tech=None, etype="full-time", **kw) -> dict:
    return dict(title=title, organization=org, employmentType=etype, location=None, startDate=start, endDate=end,
                isCurrent=current, description=kw.get("description"), highlights=kw.get("highlights", []),
                technologies=tech or [], confidence="high")


# --------------------------------------------------------------------------- months and levels


def test_year_only_dates_count_mid_year_and_ongoing_ends_today():
    assert interval("2020", "2024", False, TODAY) == (2020 * 12 + 6, 2024 * 12 + 6)  # 48 months
    s, e = interval("2023-06", None, True, TODAY)
    assert e - s == 40  # Jun 2023 -> Oct 2026
    assert interval(None, "2024", False, TODAY) is None
    assert interval("2024-05", "2024-05", False, TODAY) == (2024 * 12 + 5, 2024 * 12 + 6)  # at least 1 month


def test_overlapping_periods_are_counted_once():
    assert union_months([(0, 12), (6, 18), (30, 36)]) == 24


# --------------------------------------------------------------------------- explicit levels in the text


def test_explicit_level_is_read_per_comma_separated_segment():
    text = "Languages: Python (advanced), SQL (basic), JavaScript\nTools: Git, expert in Docker"
    assert explicit_level_from_text(text, "Python") == "advanced"
    assert explicit_level_from_text(text, "SQL") == "beginner"
    assert explicit_level_from_text(text, "JavaScript") == "unknown"  # the neighbours' levels don't leak
    assert explicit_level_from_text(text, "Docker") == "expert"
    assert explicit_level_from_text(text, "Rust") == "unknown"


def test_short_names_match_whole_words_only():
    assert explicit_level_from_text("Google Cloud (advanced)", "Go") == "unknown"
    assert explicit_level_from_text("Go (intermediate), Rust", "Go") == "intermediate"
    assert explicit_level_from_text("CSS (advanced)", "C") == "unknown"


def test_explicit_level_in_thai():
    assert explicit_level_from_text("ภาษาโปรแกรม: Python (ระดับกลาง), SQL (พื้นฐาน)", "Python") == "intermediate"
    assert explicit_level_from_text("ภาษาโปรแกรม: Python (ระดับกลาง), SQL (พื้นฐาน)", "SQL") == "beginner"


def test_aliases_are_used_to_find_the_skill_in_the_text():
    assert explicit_level_from_text("ReactJS (advanced)", "React") == "advanced"


def test_a_degree_called_master_is_not_an_expert_claim():
    assert explicit_level_from_text("Master of Science in Data Science, Python", "Python") == "unknown"


# --------------------------------------------------------------------------- inside build_result


def test_explicit_level_from_text_wins_and_unfounded_model_levels_are_dropped():
    ex = extraction(technicalSkills=[skill("Python", "expert"), skill("SQL", "unknown"), skill("Docker", "advanced")],
                    experience=[], projects=[])
    text = "Skills: Python (basic), SQL (advanced), Docker"
    skills = {s.name: s for s in build_result(ex, ctx(source_text=text)).profile.technical_skills}
    assert (skills["Python"].proficiency, skills["Python"].proficiency_basis) == ("beginner", "explicit")  # text beats model
    assert (skills["SQL"].proficiency, skills["SQL"].proficiency_basis) == ("advanced", "explicit")      # text fills what model missed
    assert (skills["Docker"].proficiency, skills["Docker"].proficiency_basis) == ("unknown", "unknown")  # model claim not in CV: dropped


def test_model_level_is_not_treated_as_evidence_when_there_is_no_text_to_check():
    ex = extraction(technicalSkills=[skill("Python", "advanced")], experience=[], projects=[])
    sk = build_result(ex, ctx(input_kind="images", source_text=None)).profile.technical_skills[0]
    assert (sk.proficiency, sk.proficiency_basis) == ("unknown", "unknown")


def test_experience_and_projects_provide_evidence_but_not_inferred_levels():
    ex = extraction(
        technicalSkills=[skill("React"), skill("Docker"), skill("Express")],
        experience=[
            job("Web Dev", "Self", "2023-06", None, True, ["React", "Next.js"], etype="freelance",
                description="Built sites", highlights=["Built storefronts with React and Next.js"]),
            job("Intern", "Siam", "2022-06", "2022-08", False, ["Express"], etype="internship"),
        ],
        projects=[],
    )
    text = "Skills: React, Docker, Express\n- Built storefronts with React and Next.js"
    res = build_result(ex, ctx(source_text=text))
    skills = {s.name: s for s in res.profile.technical_skills}
    exp_ids = {x.title: x.id for x in res.profile.experience}

    assert (skills["React"].proficiency, skills["React"].proficiency_basis) == ("unknown", "unknown")
    assert skills["React"].evidence[0].evidence_type == "experience"
    assert skills["React"].evidence[0].item_id == exp_ids["Web Dev"]
    assert "storefronts" in skills["React"].evidence[0].text  # the highlight that mentions it

    assert (skills["Express"].proficiency, skills["Express"].proficiency_basis) == ("unknown", "unknown")
    assert (skills["Docker"].proficiency, skills["Docker"].proficiency_basis) == ("unknown", "unknown")
    assert skills["Docker"].evidence[0].evidence_type == "resume_text"  # only in the skills list
    assert skills["Docker"].evidence[0].item_id is None


def test_a_certification_does_not_imply_skill_proficiency():
    ex = extraction(technicalSkills=[skill("AWS")], experience=[], projects=[], certifications=[
        dict(kind="certification", name="AWS Certified Cloud Practitioner", issuer="Amazon", date="2024", detail=None, confidence="high")])
    sk = build_result(ex, ctx(source_text="AWS Certified Cloud Practitioner 2024")).profile.technical_skills[0]
    assert (sk.proficiency, sk.proficiency_basis) == ("unknown", "unknown")


def test_undated_project_is_evidence_but_does_not_imply_proficiency():
    ex = extraction(technicalSkills=[skill("Vercel")], experience=[], projects=[
        dict(name="P", description="x", role=None, url=None, startDate=None, endDate=None, technologies=["Vercel"], confidence="high")])
    sk = build_result(ex, ctx()).profile.technical_skills[0]
    assert (sk.proficiency, sk.proficiency_basis) == ("unknown", "unknown")
    assert sk.evidence[0].evidence_type == "project"


def test_snippet_with_skill():
    text = "--- page 1 ---\nAlex\nBuilt REST APIs with Express and PostgreSQL. Led a team.\nSkills: Git"
    assert snippet_with_skill(text, "Express") == "Built REST APIs with Express and PostgreSQL."
    assert snippet_with_skill(text, "Rust") is None


# --------------------------------------------------------------------------- derived profile facts


def test_education_level_from_degree_names():
    cases = {"B.Sc.": "bachelor", "B.Eng. in Computer Engineering": "bachelor", "Bachelor of Arts": "bachelor",
             "M.Sc.": "master", "Master of Engineering": "master", "MBA": "master",
             "Ph.D.": "doctorate", "Doctor of Philosophy": "doctorate",
             "วิทยาศาสตรบัณฑิต": "bachelor", "วิทยาศาสตรมหาบัณฑิต": "master", "ปริญญาเอก ดุษฎีบัณฑิต": "doctorate",
             "Diploma in IT": "diploma", "ปวส.": "diploma", "Associate Degree": "associate", "High School": "high_school",
             "Certificate of attendance": "other"}
    for degree, level in cases.items():
        assert education_level_of(degree) == level, degree
    assert education_level_of(None) is None


def test_years_of_experience_merges_overlaps_and_ignores_volunteering():
    ex = extraction(experience=[
        job("A", "X", "2020-01", "2022-01", False),                         # 24 months
        job("B", "Y", "2021-07", "2023-01", False),                         # overlaps 6 months -> adds 12
        job("Vol", "Z", "2015-01", "2019-01", False, etype="volunteer"),   # ignored
    ], projects=[])
    assert build_result(ex, ctx()).profile.derived.years_experience == 3.0
    assert build_result(extraction(experience=[], projects=[]), ctx()).profile.derived.years_experience is None


def test_current_job_title_prefers_the_ongoing_role_else_the_latest():
    ongoing = extraction(experience=[job("Old", "A", "2018-01", "2019-01"), job("Now", "B", "2023-01", None, True)], projects=[])
    assert build_result(ongoing, ctx()).profile.derived.current_job_title == "Now"
    finished = extraction(experience=[job("Old", "A", "2018-01", "2019-01"), job("Later", "B", "2020-01", "2021-01")], projects=[])
    assert build_result(finished, ctx()).profile.derived.current_job_title == "Later"


def test_education_level_and_field_come_from_the_highest_degree():
    edu = lambda deg, field, cur=False: dict(degree=deg, fieldOfStudy=field, institution="U", startDate="2018", endDate=None if cur else "2022",
                                             isCurrent=cur, gpa=None, description=None, confidence="high")
    ex = extraction(education=[edu("B.Sc.", "Mathematics"), edu("M.Sc.", "Statistics")], experience=[], projects=[])
    d = build_result(ex, ctx()).profile.derived
    assert (d.education_level, d.field_of_study) == ("master", "Statistics")


def test_suggested_status():
    edu_now = dict(degree="B.Eng.", fieldOfStudy="CE", institution="U", startDate="2023", endDate=None, isCurrent=True, gpa=None, description=None, confidence="high")
    student = extraction(education=[edu_now], experience=[], projects=[])
    assert build_result(student, ctx()).profile.derived.suggested_status == "student"
    working = extraction(education=[], experience=[job("Dev", "A", "2022-01", None, True)], projects=[])
    assert build_result(working, ctx()).profile.derived.suggested_status == "employed"
    intern_student = extraction(education=[edu_now], experience=[job("Intern", "A", "2026-06", None, True, etype="internship")], projects=[])
    assert build_result(intern_student, ctx()).profile.derived.suggested_status == "student"  # an internship doesn't make them "employed"
    nothing = extraction(education=[], experience=[], projects=[])
    assert build_result(nothing, ctx()).profile.derived.suggested_status is None


def test_confirm_recomputes_derived_from_the_users_edits():
    res = build_result(extraction(experience=[job("Dev", "A", "2022-01", None, True)], projects=[]), ctx())
    profile = res.profile
    edited = profile.model_copy(update={"experience": [profile.experience[0].model_copy(update={"title": "Lead Dev"})]})
    assert confirm_profile(edited, TODAY).derived.current_job_title == "Lead Dev"
    # a profile that arrives without the optional blocks (older client) is still accepted and gets them
    assert derive_profile(confirm_profile(profile.model_copy(update={"derived": None}), TODAY), TODAY).years_experience is not None
