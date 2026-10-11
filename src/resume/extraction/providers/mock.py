from __future__ import annotations

import asyncio

from ...schemas.cv_extraction import CvExtraction
from ..contracts import ExtractorOutput, PreparedCv

# Matches the Figma "Review Profile" example. Synthetic data only.
MOCK_EXTRACTION_DATA: dict = {
    "isDocumentACv": True,
    "detectedLanguage": "en",
    "warnings": [],
    "personal": {
        "fullName": "Alex Example",
        "headline": "Web Developer",
        "email": "alex@example.com",
        "phone": None,
        "location": "Bangkok, Thailand",
        "links": [{"label": "GitHub", "url": "https://github.com/example"}],
        "confidence": "high",
    },
    "summary": "Computer Science graduate who builds web applications for small businesses.",
    "education": [
        {
            "degree": "B.Sc.",
            "fieldOfStudy": "Computer Science",
            "institution": "Chulalongkorn University",
            "startDate": "2020",
            "endDate": "2024",
            "isCurrent": False,
            "gpa": None,
            "description": None,
            "confidence": "medium",
        }
    ],
    "technicalSkills": [
        {"name": "JavaScript", "category": "language", "confidence": "high", "proficiency": "advanced"},
        {"name": "TypeScript", "category": "language", "confidence": "high", "proficiency": "unknown"},
        {"name": "reactjs", "category": "framework", "confidence": "high", "proficiency": "unknown"},
        {"name": "Next.js", "category": "framework", "confidence": "high", "proficiency": "unknown"},
        {"name": "Node.js", "category": "framework", "confidence": "high", "proficiency": "unknown"},
        {"name": "Express", "category": "framework", "confidence": "high", "proficiency": "unknown"},
        {"name": "postgres", "category": "database", "confidence": "high", "proficiency": "unknown"},
        {"name": "Git", "category": "devops", "confidence": "high", "proficiency": "unknown"},
        {"name": "Docker", "category": "devops", "confidence": "high", "proficiency": "unknown"},
        {"name": "Python", "category": "language", "confidence": "high", "proficiency": "unknown"},
    ],
    "softSkills": [{"name": "Teamwork", "confidence": "high"}],
    "experience": [
        {
            "title": "Freelance Web Developer",
            "organization": "Self-employed",
            "employmentType": "freelance",
            "location": None,
            "startDate": "2023-06",
            "endDate": None,
            "isCurrent": True,
            "description": "Build and maintain web applications for small businesses, including landing pages, e-commerce sites, and internal tools.",
            "highlights": [],
            "technologies": ["React", "Next.js", "Node.js", "Tailwind CSS"],
            "confidence": "high",
        }
    ],
    "projects": [
        {
            "name": "MODNOI",
            "description": "A social platform for university students to share notes, resources, and collaborate on projects.",
            "role": None,
            "url": None,
            "startDate": None,
            "endDate": None,
            "technologies": ["Next.js", "TypeScript", "PostgreSQL", "Vercel"],
            "confidence": "high",
        }
    ],
    "certifications": [
        {"kind": "workshop", "name": "AWS Workshop", "issuer": "AWS Cloud Practitioner Workshop", "date": "2024-03", "detail": None, "confidence": "high"},
        {"kind": "competition", "name": "Hackathon", "issuer": "CU Innovation Hackathon 2023", "date": "2023", "detail": "Finalist", "confidence": "high"},
        {"kind": "competition", "name": "University Competition", "issuer": "Chulalongkorn Programming Contest", "date": None, "detail": "Top 10", "confidence": "high"},
    ],
    "tools": [{"name": "VS Code", "confidence": "high"}, {"name": "Figma", "confidence": "high"}],
    "languages": [
        {"name": "Thai", "proficiency": "Native", "confidence": "high"},
        {"name": "English", "proficiency": None, "confidence": "medium"},
    ],
}


def mock_extraction() -> CvExtraction:
    return CvExtraction.model_validate(MOCK_EXTRACTION_DATA)


class MockExtractor:
    """Returns fixture data without any network call. Used for tests, CI and frontend work."""

    name = "mock"
    groundable = False

    def __init__(self, delay_ms: int = 3000):
        self.delay_ms = delay_ms

    async def extract(self, prepared: PreparedCv) -> ExtractorOutput:
        if self.delay_ms > 0:
            await asyncio.sleep(self.delay_ms / 1000)
        return ExtractorOutput(extraction=mock_extraction())
