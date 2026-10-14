"""Bounded HTML discovery for reviewed skill-learning sources."""

from collections import deque
from dataclasses import dataclass
from email.message import Message
from hashlib import sha256
from html.parser import HTMLParser
from time import monotonic, sleep
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser
import re

import requests

from src.documents.schemas.candidate_page import (
    CandidatePage,
    FetchStatus,
    ReviewStatus,
)
from src.documents.schemas.source_config import SourceConfig


USER_AGENT = "GlowJobDocumentCrawler/0.1"
DEFAULT_REQUEST_INTERVAL_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = (5, 20)
MAX_HTML_BYTES = 4 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_LINKS_PER_PAGE = 2000


@dataclass(frozen=True)
class _PageMetadata:
    title: str | None
    headings: tuple[str, ...]
    links: tuple[str, ...]
    canonical_url: str | None
    base_url: str | None


class _HTMLMetadataParser(HTMLParser):
    """Collect navigation links and lightweight metadata without retaining body text."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []
        self.headings: list[str] = []
        self.title: str | None = None
        self.og_title: str | None = None
        self.canonical_url: str | None = None
        self.base_url: str | None = None
        self._captures: list[tuple[str, list[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value for key, value in attrs if value is not None}
        tag = tag.lower()
        if tag == "a" and values.get("href") and len(self.links) < MAX_LINKS_PER_PAGE:
            self.links.append(values["href"])
        elif tag == "base" and values.get("href"):
            self.base_url = values["href"]
        elif tag == "link" and "canonical" in values.get("rel", "").lower().split():
            self.canonical_url = values.get("href")
        elif tag == "meta":
            if values.get("property", "").lower() == "og:title":
                self.og_title = values.get("content")
        if tag == "title" or tag in {"h1", "h2", "h3"}:
            self._captures.append((tag, []))

    def handle_data(self, data: str) -> None:
        for _, parts in self._captures:
            parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self._captures) - 1, -1, -1):
            capture_tag, parts = self._captures[index]
            if capture_tag == tag:
                text = " ".join(" ".join(parts).split())
                del self._captures[index:]
                if not text:
                    return
                if tag == "title" and self.title is None:
                    self.title = text
                elif tag in {"h1", "h2", "h3"}:
                    self.headings.append(text)
                return

    def result(self) -> _PageMetadata:
        title = next(
            (value for value in (self.headings[0] if self.headings else None, self.title, self.og_title) if value),
            None,
        )
        return _PageMetadata(
            title=title,
            headings=tuple(self.headings),
            links=tuple(self.links),
            canonical_url=self.canonical_url,
            base_url=self.base_url,
        )


class _RobotsPolicy:
    """Fetch and cache robots rules for each origin; fail closed on server/network errors."""

    def __init__(self, session: requests.Session) -> None:
        self._session = session
        self._rules: dict[str, RobotFileParser | None] = {}
        self._delays: dict[str, float] = {}

    def can_fetch(self, url: str) -> bool:
        origin = _origin(url)
        if origin not in self._rules:
            self._load(origin)
        parser = self._rules[origin]
        if parser is None:
            return False
        return parser.can_fetch(USER_AGENT, url)

    def crawl_delay(self, url: str) -> float | None:
        origin = _origin(url)
        if origin not in self._rules:
            self._load(origin)
        return self._delays.get(origin)

    def _load(self, origin: str) -> None:
        robots_url = f"{origin}/robots.txt"
        parser = RobotFileParser(robots_url)
        try:
            response = self._session.get(
                robots_url,
                timeout=REQUEST_TIMEOUT_SECONDS,
                allow_redirects=True,
            )
        except requests.RequestException:
            self._rules[origin] = None
            return

        if 200 <= response.status_code < 300:
            parser.parse(response.text.splitlines())
            self._rules[origin] = parser
            delay = parser.crawl_delay(USER_AGENT)
            self._delays[origin] = float(delay) if delay is not None else 0.0
        elif 400 <= response.status_code < 500 and response.status_code != 429:
            # RFC 9309 treats 4xx robots.txt responses as unavailable.
            parser.parse([])
            self._rules[origin] = parser
            self._delays[origin] = 0.0
        else:
            # A 429 or server/network error is treated conservatively.
            self._rules[origin] = None
        response.close()


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")


def _normalize_url(url: str) -> str:
    without_fragment, _ = urldefrag(url.strip())
    parsed = urlsplit(without_fragment)
    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.port is not None and not (
        (scheme == "http" and parsed.port == 80)
        or (scheme == "https" and parsed.port == 443)
    ):
        netloc = f"{hostname}:{parsed.port}"
    else:
        netloc = hostname
    path = parsed.path or "/"
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def _path_is_allowed(path: str, prefix: str) -> bool:
    normalized = prefix.rstrip("/") or "/"
    if normalized == "/":
        return path.startswith("/")
    return path == normalized or path.startswith(f"{normalized}/")


def _is_in_scope(url: str, config: SourceConfig) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    if parsed.hostname.lower().rstrip(".") not in config.allowed_hosts:
        return False
    path = parsed.path or "/"
    if not any(_path_is_allowed(path, prefix) for prefix in config.allowed_path_prefixes):
        return False
    folded_path = path.casefold()
    if any(pattern.casefold() in folded_path for pattern in config.exclude_patterns):
        return False
    if config.include_patterns and not any(
        pattern.casefold() in folded_path for pattern in config.include_patterns
    ):
        return False
    return True


def _decode_html(body: bytes, content_type_header: str) -> str:
    """Decode HTML using its HTTP charset, then its meta charset, then UTF-8."""
    message = Message()
    message["content-type"] = content_type_header
    encoding = message.get_content_charset()
    if encoding is None:
        match = re.search(rb"charset\s*=\s*[\"']?([A-Za-z0-9._-]+)", body[:8192], re.IGNORECASE)
        encoding = match.group(1).decode("ascii") if match else "utf-8"
    try:
        return body.decode(encoding, errors="replace")
    except LookupError:
        return body.decode("utf-8", errors="replace")

class BoundedHTMLCrawler:
    """Discover in-scope HTML pages and return records for human review."""

    def __init__(
        self,
        *,
        request_interval_seconds: float = DEFAULT_REQUEST_INTERVAL_SECONDS,
        timeout: tuple[float, float] = REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        if request_interval_seconds < 0:
            raise ValueError("request_interval_seconds must not be negative")
        self.request_interval_seconds = request_interval_seconds
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            }
        )
        self.robots = _RobotsPolicy(self.session)
        self._last_request_by_origin: dict[str, float] = {}

    def crawl(self, config: SourceConfig) -> list[CandidatePage]:
        """Crawl one source config breadth-first within its configured limits."""
        queue: deque[tuple[str, int]] = deque()
        queued: set[str] = set()
        for seed in config.seed_urls:
            normalized = _normalize_url(seed)
            if _is_in_scope(normalized, config) and normalized not in queued:
                queue.append((normalized, 0))
                queued.add(normalized)

        if not queue:
            raise ValueError(f"Source config {config.id!r} has no in-scope seed URLs")

        candidates: list[CandidatePage] = []
        canonical_seen: set[str] = set()
        attempted = 0
        while queue and attempted < config.max_pages:
            url, depth = queue.popleft()
            attempted += 1
            candidate, links, _body, _content_type_header = self._inspect_url(url, depth, config)
            canonical_key = candidate.canonical_url or candidate.url
            if candidate.fetch_status == FetchStatus.FETCHED and canonical_key in canonical_seen:
                continue
            if candidate.fetch_status == FetchStatus.FETCHED:
                canonical_seen.add(canonical_key)
            candidates.append(candidate)

            if (
                candidate.fetch_status != FetchStatus.FETCHED
                or depth >= config.max_depth
            ):
                continue
            for link in links:
                try:
                    absolute = _normalize_url(urljoin(url, link))
                except ValueError:
                    continue
                if absolute in queued or not _is_in_scope(absolute, config):
                    continue
                queued.add(absolute)
                queue.append((absolute, depth + 1))
        return candidates

    def fetch_approved_page(
        self, url: str, config: SourceConfig
    ) -> tuple[CandidatePage, bytes | None, str | None]:
        """Fetch one reviewed URL using the crawler's scope and safety limits."""
        normalized = _normalize_url(url)
        if not _is_in_scope(normalized, config):
            raise ValueError(f"Approved URL is outside source scope: {url}")
        candidate, _links, body, content_type_header = self._inspect_url(normalized, 0, config)
        return candidate, body, content_type_header

    def close(self) -> None:
        self.session.close()

    def _wait_for_origin(self, url: str) -> None:
        origin = _origin(url)
        robots_delay = self.robots.crawl_delay(url) or 0.0
        interval = max(self.request_interval_seconds, robots_delay)
        previous = self._last_request_by_origin.get(origin)
        if previous is not None:
            remaining = interval - (monotonic() - previous)
            if remaining > 0:
                sleep(remaining)
        self._last_request_by_origin[origin] = monotonic()

    def _inspect_url(
        self, url: str, depth: int, config: SourceConfig
    ) -> tuple[CandidatePage, tuple[str, ...], bytes | None, str | None]:
        if not self.robots.can_fetch(url):
            return self._candidate(
                config,
                url,
                depth,
                FetchStatus.BLOCKED_BY_ROBOTS,
                error_message="robots.txt does not allow this URL or could not be reached",
            ), (), None, None

        current_url = url
        response: requests.Response | None = None
        try:
            for redirect_count in range(MAX_REDIRECTS + 1):
                if not _is_in_scope(current_url, config):
                    raise ValueError("Redirect target is outside configured host/path boundaries")
                if not self.robots.can_fetch(current_url):
                    return self._candidate(
                        config,
                        url,
                        depth,
                        FetchStatus.BLOCKED_BY_ROBOTS,
                        error_message="robots.txt does not allow the redirect target",
                    ), (), None, None
                self._wait_for_origin(current_url)
                response = self.session.get(
                    current_url,
                    timeout=self.timeout,
                    allow_redirects=False,
                    stream=True,
                )
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    response.close()
                    response = None
                    if not location or redirect_count == MAX_REDIRECTS:
                        raise ValueError("Too many redirects or redirect without a Location")
                    current_url = _normalize_url(urljoin(current_url, location))
                    continue
                break
            else:
                raise ValueError("Too many redirects")

            if response is None:
                raise ValueError("No response received")
            content_type_header = response.headers.get("Content-Type", "")
            content_type = content_type_header.split(";", 1)[0].strip().lower()
            if response.status_code < 200 or response.status_code >= 300:
                return self._candidate(
                    config,
                    url,
                    depth,
                    FetchStatus.FAILED,
                    content_type=content_type or None,
                    http_status=response.status_code,
                    error_message=f"HTTP {response.status_code}",
                ), (), None, None
            if content_type not in config.allowed_content_types or content_type != "text/html":
                return self._candidate(
                    config,
                    url,
                    depth,
                    FetchStatus.UNSUPPORTED_CONTENT_TYPE,
                    content_type=content_type or None,
                    http_status=response.status_code,
                    error_message="Only configured HTML pages are parsed during discovery",
                ), (), None, None

            chunks: list[bytes] = []
            byte_count = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                byte_count += len(chunk)
                if byte_count > MAX_HTML_BYTES:
                    raise ValueError(f"HTML page exceeds the {MAX_HTML_BYTES}-byte limit")
                chunks.append(chunk)
            body = b"".join(chunks)
            parser = _HTMLMetadataParser()
            parser.feed(_decode_html(body, content_type_header))
            metadata = parser.result()
            canonical = _normalize_url(urljoin(current_url, metadata.canonical_url)) if metadata.canonical_url else current_url
            if not _is_in_scope(canonical, config):
                canonical = current_url
            content_hash = sha256(body).hexdigest()
            candidate = self._candidate(
                config,
                url,
                depth,
                FetchStatus.FETCHED,
                canonical_url=canonical,
                title=metadata.title,
                content_type=content_type,
                headings=metadata.headings,
                content_hash=content_hash,
                http_status=response.status_code,
            )
            base_url = urljoin(current_url, metadata.base_url) if metadata.base_url else current_url
            return candidate, tuple(urljoin(base_url, link) for link in metadata.links), body, content_type_header
        except (requests.RequestException, ValueError) as error:
            return self._candidate(
                config,
                url,
                depth,
                FetchStatus.FAILED,
                error_message=str(error),
            ), (), None, None
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def _candidate(
        config: SourceConfig,
        url: str,
        depth: int,
        status: FetchStatus,
        **values: object,
    ) -> CandidatePage:
        page_title = values.pop("title", None) or config.title
        publisher = values.pop("publisher", None) or config.publisher
        source_type = values.pop("source_type", None) or config.source_type
        return CandidatePage(
            source_config_id=config.id,
            url=url,
            crawl_depth=depth,
            career_tracks=config.career_tracks,
            skills=config.skills,
            fetch_status=status,
            review_status=(ReviewStatus.PENDING if config.review_required else ReviewStatus.APPROVED),
            title=page_title,
            publisher=publisher,
            source_type=source_type,
            **values,
        )
