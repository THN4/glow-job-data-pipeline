"""Synthetic CV and PDF fixtures for the reusable resume-processing tests."""

from __future__ import annotations

import io

import pymupdf
from PIL import Image, ImageDraw, ImageFont

SAMPLE_CV_LINES = [
    "# Alex Example",
    "Full-Stack Web Developer | Bangkok, Thailand",
    "alex.example@example.com | github.com/alex-example",
    "",
    "## Education",
    "B.Sc. in Computer Science, Chulalongkorn University, 2020 - 2024",
    "GPA 3.45 / 4.00",
    "",
    "## Experience",
    "Freelance Web Developer, Self-employed, Jun 2023 - Present",
    "- Build and maintain web applications for small businesses (landing pages, e-commerce, internal tools)",
    "- Tech: ReactJS, Next.js, Node.js, Tailwind CSS",
    "Software Engineer Intern, Siam Digital Co., Ltd., Jun 2022 - Aug 2022",
    "- Built REST APIs with Express and PostgreSQL",
    "",
    "## Projects",
    "MODNOI - A social platform for university students to share notes and collaborate on projects.",
    "Tech: Next.js, TypeScript, PostgreSQL, Vercel",
    "",
    "## Skills",
    "Languages: JavaScript, TypeScript, Python",
    "Frameworks: React, Next.js, Express",
    "Databases: Postgres, MongoDB",
    "Tools: Git, Docker, Figma, VS Code",
    "",
    "## Certifications & Activities",
    "AWS Cloud Practitioner Workshop - Mar 2024",
    "CU Innovation Hackathon 2023 - Finalist",
    "Chulalongkorn Programming Contest - Top 10",
    "",
    "## Languages",
    "Thai (Native), English (IELTS 7.0)",
]


def make_text_pdf(lines: list[str] = SAMPLE_CV_LINES) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 50.0
    for raw in lines:
        if y > 790:
            page = doc.new_page(width=595, height=842)
            y = 50.0
        h1, h2 = raw.startswith("# "), raw.startswith("## ")
        size = 20 if h1 else 13 if h2 else 10
        page.insert_text((50, y), raw.lstrip("# "), fontsize=size, fontname="hebo" if h1 or h2 else "helv")
        y += 28 if h1 else 22 if h2 else 15
    output = doc.tobytes()
    doc.close()
    return output


def make_cv_image(lines: list[str] = SAMPLE_CV_LINES) -> bytes:
    width, y = 1240, 60
    rows: list[tuple[int, str, int]] = []
    for raw in lines:
        h1, h2 = raw.startswith("# "), raw.startswith("## ")
        size = 40 if h1 else 28 if h2 else 21
        rows.append((y, raw.lstrip("# "), size))
        y += 56 if h1 else 46 if h2 else 32
    image = Image.new("RGB", (width, y + 40), "white")
    draw = ImageDraw.Draw(image)
    for row_y, text, size in rows:
        draw.text((60, row_y), text, fill="black", font=ImageFont.load_default(size=size))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def make_scanned_pdf() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=make_cv_image(), keep_proportion=True)
    output = doc.tobytes()
    doc.close()
    return output


def make_many_pages_pdf(pages: int) -> bytes:
    doc = pymupdf.open()
    for index in range(pages):
        doc.new_page(width=595, height=842).insert_text((50, 50), f"Page {index + 1}")
    output = doc.tobytes()
    doc.close()
    return output


def make_encrypted_pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 50), "secret")
    output = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    doc.close()
    return output


def make_two_column_pdf() -> bytes:
    """A compact two-column page. PDF content order places the sidebar first."""
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.draw_rect(pymupdf.Rect(0, 0, 190, 842), color=None, fill=(0.93, 0.95, 0.98))
    left = [
        "Maya",
        "Okafor",
        "UX / UI Designer",
        "NN/g UX Certification",
        "Portfolio: maya-okafor.example",
        "Contact: maya.okafor@example.com",
    ]
    right = [
        "Profile",
        "Senior UX Designer",
        "Research-driven product designer",
        "Experienced in user interviews and usability testing",
        "Creates accessible interfaces for web and mobile products",
    ]
    for index, text in enumerate(left):
        page.insert_text((24, 55 + index * 32), text, fontsize=10)
    for index, text in enumerate(right):
        page.insert_text((215, 55 + index * 32), text, fontsize=10)
    output = doc.tobytes()
    doc.close()
    return output
