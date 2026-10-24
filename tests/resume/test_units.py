"""Unit tests: schemas, skill aliases, preprocessing, post-processing. No network, no model."""

import pytest
from pydantic import ValidationError

from src.resume.errors import ResumeProcessingError
from src.resume.extraction.providers.mock import mock_extraction
from src.resume.normalization.postprocess import (
    BuildContext,
    build_result,
    confirm_profile,
    fix_range,
    make_grounder,
    normalize_date_format,
    valid_date,
)
from src.resume.parsing.preprocess import Limits, detect_mime, is_usable_page_text, prepare_cv
from src.resume.schemas.cv_extraction import (
    CvExtraction,
    CvExtractionResult,
    CvProfile,
    cv_extraction_json_schema,
    empty_profile,
)
from src.resume.normalization.skill_aliases import normalize_skill_name, skill_spellings

from .fixtures import (
    make_cv_image,
    make_encrypted_pdf,
    make_many_pages_pdf,
    make_scanned_pdf,
    make_text_pdf,
)

LIMITS = Limits(max_pdf_pages=10, max_image_pages=4)


def ctx(**kw) -> BuildContext:
    base = dict(extraction_id="job_1", model="test", duration_ms=1, input_kind="text", page_count=1)
    return BuildContext(**{**base, **kw})


# --------------------------------------------------------------------------- schemas


def test_mock_and_empty_profile_are_valid():
    assert mock_extraction().is_document_a_cv
    assert CvProfile.model_validate(empty_profile().model_dump(by_alias=True))


def test_json_schema_is_inlined_camelcase_and_strict():
    schema = cv_extraction_json_schema()
    assert "$ref" not in str(schema) and "$defs" not in schema
    assert schema["additionalProperties"] is False
    assert "technicalSkills" in schema["required"]
    assert "isDocumentACv" in schema["properties"]


def test_json_schema_keeps_fields_named_title():
    # Regression: stripping "title" annotations must not drop the experience "title" field.
    props = cv_extraction_json_schema()["properties"]["experience"]["items"]["properties"]
    assert "title" in props and "title" in cv_extraction_json_schema()["properties"]["experience"]["items"]["required"]
    assert "title" not in props["title"]  # the annotation inside it is gone


def test_ai_output_rejects_unknown_keys():
    data = mock_extraction().model_dump(by_alias=True)
    data["surprise"] = 1
    with pytest.raises(ValidationError):
        CvExtraction.model_validate(data)


def test_profile_uses_camelcase_on_the_wire():
    wire = build_result(mock_extraction(), ctx()).profile.model_dump(mode="json", by_alias=True)
    edu = wire["education"][0]
    assert {"id", "needsReview", "source", "fieldOfStudy", "startDate"} <= edu.keys()
    assert wire["schemaVersion"] == 1


# --------------------------------------------------------------------------- skill aliases


def test_skill_aliases():
    assert normalize_skill_name("reactjs") == "React"
    assert normalize_skill_name(" Postgres ") == "PostgreSQL"
    assert normalize_skill_name("k8s") == "Kubernetes"
    assert normalize_skill_name("  Elixir  ") == "Elixir"
    assert {"react", "reactjs", "react.js"} <= set(skill_spellings("React"))


# --------------------------------------------------------------------------- preprocess


def test_text_pdf_is_sent_as_text():
    p = prepare_cv(make_text_pdf(), LIMITS)
    assert p.kind == "text" and p.page_count == 1
    assert "Chulalongkorn University" in p.text and "--- page 1 ---" in p.text


def test_scanned_pdf_is_rendered_to_images():
    p = prepare_cv(make_scanned_pdf(), LIMITS)
    assert p.kind == "images" and len(p.images) == 1 and p.images[0].mime == "image/jpeg"


def test_photo_becomes_a_jpeg():
    p = prepare_cv(make_cv_image(), LIMITS)
    assert p.kind == "images" and p.page_count == 1


def test_too_many_pages():
    with pytest.raises(ResumeProcessingError) as e:
        prepare_cv(make_many_pages_pdf(11), LIMITS)
    assert e.value.code == "TOO_MANY_PAGES"


def test_scanned_pages_are_limited_with_a_warning():
    import pymupdf

    src = pymupdf.open(stream=make_scanned_pdf(), filetype="pdf")
    out = pymupdf.open()
    for _ in range(6):
        out.insert_pdf(src)
    p = prepare_cv(out.tobytes(), Limits(max_pdf_pages=10, max_image_pages=2))
    assert p.kind == "images" and len(p.images) == 2
    assert "PDF page(s) 3, 4, 5, 6" in p.warnings[0]


def test_corrupt_and_encrypted_pdfs_are_unreadable():
    for data in (b"%PDF-1.7\nthis is not really a pdf", make_encrypted_pdf()):
        with pytest.raises(ResumeProcessingError) as e:
            prepare_cv(data, LIMITS)
        assert e.value.code in ("UNREADABLE_DOCUMENT", "UNSUPPORTED_FILE_TYPE")


def test_non_pdf_non_image_is_rejected():
    with pytest.raises(ResumeProcessingError) as e:
        detect_mime(b"hello world")
    assert e.value.code == "UNSUPPORTED_FILE_TYPE"


def test_two_column_pdf_keeps_columns_together():
    from .fixtures import make_two_column_pdf

    text = prepare_cv(make_two_column_pdf(), LIMITS).text
    # the whole sidebar comes before the main column (not interleaved line by line)
    assert text.index("NN/g UX Certification") < text.index("Senior UX Designer")
    assert text.index("Maya") < text.index("Okafor") < text.index("UX / UI Designer") < text.index("Profile")


def test_soft_hyphens_next_to_digits_become_dashes():
    from src.resume.parsing.preprocess import _clean_text

    assert _clean_text("081­000­0002 and 2559 ­ 2563") == "081-000-0002 and 2559 - 2563"
    assert _clean_text("a b") == "a b"  # non-breaking spaces become plain spaces
    assert _clean_text("infra­structure") == "infra­structure"  # inside a word: untouched


def test_is_usable_page_text():
    assert not is_usable_page_text("")
    assert not is_usable_page_text("  ")
    assert not is_usable_page_text("�" * 200)
    assert is_usable_page_text("Experienced developer " * 10)


# --------------------------------------------------------------------------- postprocess


def test_result_is_schema_valid_with_ids():
    result = build_result(mock_extraction(), ctx())
    CvExtractionResult.model_validate(result.model_dump(by_alias=True))
    assert result.profile.education[0].id.startswith("edu_")
    assert result.profile.education[0].source == "cv"


def with_skills(skills: list[dict]) -> CvExtraction:
    data = mock_extraction().model_dump(by_alias=True)
    data["technicalSkills"] = skills
    return CvExtraction.model_validate(data)


def test_profile_skills_keep_raw_labels_and_only_dedupe_case_variants():
    ex = with_skills([
        {"name": "reactjs", "category": "framework", "confidence": "low", "proficiency": "unknown"},
        {"name": "React", "category": "framework", "confidence": "high", "proficiency": "unknown"},
        {"name": "REACT", "category": "framework", "confidence": "high", "proficiency": "unknown"},
        {"name": "postgres", "category": "database", "confidence": "high", "proficiency": "unknown"},
    ])
    skills = build_result(ex, ctx()).profile.technical_skills
    assert [(s.name, s.raw_name, s.confidence) for s in skills] == [
        ("reactjs", "reactjs", "low"),
        ("React", "React", "high"),
        ("postgres", "postgres", "high"),
    ]


def test_review_flags_for_low_confidence_and_missing_key_fields():
    ex = mock_extraction()
    ex.education[0].confidence = "high"
    ex.education[0].institution = None
    ex.experience[0].confidence = "medium"
    result = build_result(ex, ctx())
    assert result.profile.education[0].needs_review
    assert result.profile.experience[0].needs_review
    assert result.meta.review_count >= 2


def test_grounding_check_downgrades_invented_items():
    ex = mock_extraction()
    invented = ex.experience[0].model_copy(update={"title": "Senior Architect", "organization": "Invented Corp"})
    ex.experience = [ex.experience[0], invented]
    source = "Alex Example\nFreelance Web Developer, Self-employed, Jun 2023 - Present\nReactJS, Next.js"
    exp = build_result(ex, ctx(source_text=source)).profile.experience
    assert exp[0].confidence == "high"
    assert exp[1].confidence == "low" and exp[1].needs_review


def test_grounding_uses_skill_aliases():
    ex = with_skills([
        {"name": "React", "category": "framework", "confidence": "high", "proficiency": "unknown"},
        {"name": "Kubernetes", "category": "devops", "confidence": "high", "proficiency": "unknown"},
    ])
    result = build_result(ex, ctx(source_text="Skills: ReactJS, Docker"))
    assert {s.name: s.confidence for s in result.profile.technical_skills} == {"React": "high", "Kubernetes": "low"}


def test_grounding_also_covers_soft_skills_and_languages():
    ex = mock_extraction()  # has "Teamwork", "Thai", "English"
    result = build_result(ex, ctx(source_text="Languages: Thai (Native). Skills: Python"))
    assert {i.name: i.confidence for i in result.profile.soft_skills} == {"Teamwork": "low"}
    langs = {i.name: i.confidence for i in result.profile.languages}
    assert langs["Thai"] == "high" and langs["English"] == "low"


def test_invalid_email_and_links_are_dropped_with_warnings():
    ex = mock_extraction()
    ex.personal.email = "not-an-email"
    ex.personal.links = [type(ex.personal.links[0])(label="Site", url="exa mple")]
    result = build_result(ex, ctx())
    assert result.profile.personal.email is None and result.profile.personal.links == []
    assert len(result.meta.warnings) >= 2


def test_scheme_is_added_to_links():
    ex = mock_extraction()
    ex.personal.links = [type(ex.personal.links[0])(label="GitHub", url="github.com/alex")]
    assert build_result(ex, ctx()).profile.personal.links[0].url == "https://github.com/alex"


def test_dates():
    assert valid_date("2024") == "2024" and valid_date("2023-06") == "2023-06"
    assert valid_date("2023-13") is None and valid_date("sometime in 2023") is None  # "June 2023" is now understood (see loose-format test)
    assert valid_date("1900") is None and valid_date(None) is None
    assert fix_range("2024", "2020", False)[1] == "low"
    assert fix_range("2020", "2024", False)[1] == "high"
    current_dates, current_confidence = fix_range("2023-06", "2024", True)
    assert current_dates["end_date"] is None and current_confidence == "low"
    assert fix_range("sometime in 2023", None, True)[1] == "low"


def test_loose_date_formats_are_understood_and_not_flagged():
    cases = {"Jun 2023": "2023-06", "June 2023": "2023-06", "Sept. 2022": "2022-09", "2023 June": "2023-06",
             "06/2023": "2023-06", "2023/6": "2023-06", "2023-6": "2023-06", "2023": "2023", "มิถุนายน 2563": "2563-06",
             "พ.ค. 2562": "2562-05"}
    for raw, expected in cases.items():
        assert normalize_date_format(raw) == expected, raw
    assert normalize_date_format("Present") is None and normalize_date_format("Foo 2023") is None
    assert normalize_date_format("13/2023") is None
    assert valid_date("Jun 2023") == "2023-06"
    dates, conf = fix_range("Jun 2023", "Aug 2023", False)
    assert (dates["start_date"], dates["end_date"], conf) == ("2023-06", "2023-08", "high")  # only reformatted
    assert fix_range("Foo 2023", None, True)[1] == "low"  # not understood -> discarded and flagged
    assert fix_range("มิถุนายน 2563", None, True)[0]["start_date"] == "2020-06"  # Buddhist Era converted (and flagged)
    assert fix_range("มิถุนายน 2563", None, True)[1] == "low"


def test_buddhist_era_years_are_converted_and_flagged():
    assert valid_date("2563") == "2020" and valid_date("2559-06") == "2016-06"
    assert valid_date("2300") is None and valid_date("2900") is None  # not plausible as BE either
    dates, conf = fix_range("2559", "2563", False)
    assert (dates["start_date"], dates["end_date"], conf) == ("2016", "2020", "low")  # converted -> user confirms

    ex = mock_extraction()
    ex.education[0].start_date, ex.education[0].end_date = "2559", "2563"
    edu = build_result(ex, ctx()).profile.education[0]
    assert (edu.start_date, edu.end_date, edu.needs_review) == ("2016", "2020", True)


def test_grounder():
    ground = make_grounder("B.Sc. in Computer Science, Chulalongkorn  University, 2020 - 2024\nSkills: Go, C#, Node.js")
    assert ground("chulalongkorn university") and not ground("Mahidol University")
    assert ground("Go") and ground("C#") and not ground("R")
    assert make_grounder("จุฬาลงกรณ์มหาวิทยาลัย คณะวิศวกรรมศาสตร์")("จุฬาลงกรณ์มหาวิทยาลัย")


def test_confirm_profile_clears_review_flags():
    profile = build_result(mock_extraction(), ctx()).profile
    confirmed = confirm_profile(profile)
    flags = [confirmed.personal, *confirmed.education, *confirmed.technical_skills, *confirmed.experience]
    assert all(i.needs_review is False for i in flags)
