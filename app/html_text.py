"""Safe rendering of meeting descriptions. Scripts and unsafe links are removed."""

from __future__ import annotations

import html
from html.parser import HTMLParser
from urllib.parse import urlparse

_ALLOWED = {
    "p",
    "br",
    "div",
    "span",
    "b",
    "strong",
    "i",
    "em",
    "u",
    "ul",
    "ol",
    "li",
    "a",
    "blockquote",
    "h1",
    "h2",
    "h3",
    "h4",
    "table",
    "tr",
    "td",
    "th",
    "thead",
    "tbody",
}
_SKIP = {"script", "style", "iframe", "object", "embed", "head", "meta", "link"}


def _safe_href(href: str) -> bool:
    candidate = href.strip()
    lowered = candidate.lower()
    if not candidate or lowered.startswith(("javascript:", "data:", "vbscript:")):
        return False
    parsed = urlparse(candidate)
    return parsed.scheme in {"http", "https", "mailto"}


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SKIP:
            self._skip += 1
            return
        if self._skip or tag not in _ALLOWED:
            return
        if tag == "br":
            self.parts.append("<br>")
            return
        if tag == "a":
            href = ""
            for key, value in attrs:
                if key.lower() == "href" and value:
                    href = value.strip()
            if _safe_href(href):
                self.parts.append(f'<a href="{html.escape(href, quote=True)}">')
            else:
                self.parts.append("<a>")
            return
        self.parts.append(f"<{tag}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _SKIP:
            if self._skip:
                self._skip -= 1
            return
        if self._skip or tag not in _ALLOWED or tag == "br":
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(html.escape(data))


def sanitize_html(value: str) -> str:
    if not value:
        return ""
    parser = _Sanitizer()
    parser.feed(value[:100_000])
    parser.close()
    return "".join(parser.parts)


def html_to_text(value: str) -> str:
    class TextParser(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self._skip = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            lowered = tag.lower()
            if lowered in _SKIP:
                self._skip += 1
            if lowered in {"br", "p", "div", "li", "tr"}:
                self.parts.append("\n")

        def handle_endtag(self, tag: str) -> None:
            lowered = tag.lower()
            if lowered in _SKIP and self._skip:
                self._skip -= 1
            if lowered in {"p", "div", "li", "tr"}:
                self.parts.append("\n")

        def handle_data(self, data: str) -> None:
            if not self._skip:
                self.parts.append(data)

    parser = TextParser()
    parser.feed(value or "")
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line).strip()


def body_to_html(body_html: str, body_text: str) -> str:
    if body_html.strip():
        return sanitize_html(body_html)
    if body_text.strip():
        return "<p>" + html.escape(body_text).replace("\n", "<br>") + "</p>"
    return ""
