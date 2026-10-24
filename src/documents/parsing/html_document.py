"""Extract readable heading-based sections from HTML documentation pages."""

from dataclasses import asdict, dataclass
import re
from html.parser import HTMLParser
from typing import Any


_IGNORED_TAGS = {"script", "style", "noscript", "svg", "header", "footer", "aside", "form", "button"}
_IGNORED_CLASS_MARKERS = {"breadcrumb", "related", "sphinxsidebar", "sidebar", "toctree-wrapper", "contents local", "navigation"}
_BLOCK_TAGS = {"p", "li", "pre", "blockquote", "td", "th", "dt", "dd"}
_HEADING_RE = re.compile(r"^h([1-6])$")


@dataclass(frozen=True)
class ParsedSection:
    """A content block grouped under its document heading path."""

    heading_path: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class ParsedHTMLDocument:
    """Normalized page metadata and section text, ready for human review."""

    title: str | None
    sections: tuple[ParsedSection, ...]

    def to_record(self) -> dict[str, Any]:
        record = asdict(self)
        record["sections"] = [
            {"heading_path": list(section.heading_path), "text": section.text}
            for section in self.sections
        ]
        return record


class _ContentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ignored_depth = 0
        self.ignored_roots: list[str] = []
        self.main_depth = 0
        self.main_blocks: list[tuple[str, str, bool]] = []
        self.all_blocks: list[tuple[str, str, bool]] = []
        self.current_tag: str | None = None
        self.current_parts: list[str] = []
        self.current_main = False
        self.title_parts: list[str] = []
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if self.in_title:
            return
        if tag in _IGNORED_TAGS:
            self.ignored_depth += 1
            self.ignored_roots.append(tag)
            return
        if self.ignored_depth:
            return
        classes = set(attributes.get("class", "").casefold().split())
        aria_label = attributes.get("aria-label", "").casefold()
        if any(marker in classes for marker in _IGNORED_CLASS_MARKERS) or "breadcrumb" in aria_label:
            self.ignored_depth += 1
            self.ignored_roots.append(tag)
            return
        if tag == "title":
            self.in_title = True
            return
        if tag in {"main", "article"} or attributes.get("role") == "main":
            self.main_depth += 1
        if _HEADING_RE.match(tag):
            self._flush()
            self.current_tag = tag
            self.current_parts = []
            self.current_main = self.main_depth > 0
        elif tag in _BLOCK_TAGS:
            self._flush()
            self.current_tag = tag
            self.current_parts = []
            self.current_main = self.main_depth > 0
        elif tag == "br" and self.current_tag is not None:
            self.current_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self.in_title:
            self.in_title = False
            return
        if self.ignored_depth:
            for index in range(len(self.ignored_roots) - 1, -1, -1):
                if self.ignored_roots[index] == tag:
                    del self.ignored_roots[index]
                    self.ignored_depth -= 1
                    break
            return
        if self.current_tag == tag:
            self._flush()
        if tag in {"main", "article"} and self.main_depth:
            self.main_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        elif not self.ignored_depth and self.current_tag is not None:
            self.current_parts.append(data)

    def close(self) -> None:
        super().close()
        self._flush()

    def _flush(self) -> None:
        if self.current_tag is None:
            return
        raw_text = "".join(self.current_parts)
        if self.current_tag == "pre":
            code = raw_text.strip("\n\r")
            fence = "`" * max(3, max((len(run) for run in re.findall(r"`+", code)), default=0) + 1)
            text = f"{fence}text\n{code}\n{fence}" if code.strip() else ""
        else:
            text = re.sub(r"\s+", " ", raw_text).strip()
        if text:
            block = (self.current_tag, text, self.current_main)
            self.all_blocks.append(block)
            if self.current_main:
                self.main_blocks.append(block)
        self.current_tag = None
        self.current_parts = []
        self.current_main = False


def parse_html_document(html: str) -> ParsedHTMLDocument:
    """Extract title and content blocks, preferring main/article content."""
    parser = _ContentParser()
    parser.feed(html)
    parser.close()
    blocks = parser.main_blocks or parser.all_blocks
    title = re.sub(r"\s+", " ", " ".join(parser.title_parts)).strip() or None

    headings: list[tuple[int, str]] = []
    grouped: list[ParsedSection] = []
    body_parts: list[str] = []

    def flush() -> None:
        if body_parts:
            path = tuple(label for _level, label in headings) or ((title,) if title else ())
            if path:
                grouped.append(ParsedSection(path, "\n\n".join(body_parts)))
            body_parts.clear()

    for tag, text, _in_main in blocks:
        match = _HEADING_RE.match(tag)
        if match:
            flush()
            level = int(match.group(1))
            while headings and headings[-1][0] >= level:
                headings.pop()
            headings.append((level, text))
        else:
            body_parts.append(text)
    flush()
    return ParsedHTMLDocument(title=title, sections=tuple(grouped))
