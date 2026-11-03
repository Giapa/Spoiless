"""Read EPUB content as unconfirmed, ordered spine sections."""

from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import PurePosixPath
from posixpath import dirname, join, normpath
from urllib.parse import unquote, urlsplit
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
MAX_UNPACKED_BYTES = 100 * 1024 * 1024
MAX_ENTRIES = 2000


class InvalidEpub(ValueError):
    """The file cannot safely be imported as a supported EPUB."""


@dataclass(frozen=True)
class Section:
    text: str


@dataclass(frozen=True)
class NavigationEntry:
    """An unconfirmed navigation link; unresolved links have no position."""

    title: str
    section_position: int | None
    character_offset: int | None


@dataclass(frozen=True)
class Book:
    title: str
    sections: tuple[Section, ...]
    navigation: tuple[NavigationEntry, ...] = ()


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0
        self.raw_length = 0
        self.anchors: dict[str, int | None] = {}

    def append(self, text: str) -> None:
        self.parts.append(text)
        self.raw_length += len(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style"}:
            self.hidden_depth += 1
        elif not self.hidden_depth and tag.lower() in {
            "p",
            "br",
            "div",
            "li",
            "h1",
            "h2",
            "h3",
        }:
            self.append("\n")
        if not self.hidden_depth:
            for key, value in attrs:
                if key == "id" and value:
                    self.anchors[value] = (
                        self.raw_length if value not in self.anchors else None
                    )

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style"} and self.hidden_depth:
            self.hidden_depth -= 1
        elif not self.hidden_depth and tag.lower() in {
            "p",
            "div",
            "li",
            "h1",
            "h2",
            "h3",
        }:
            self.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.append(data)

    def extract(self) -> tuple[str, dict[str, int | None]]:
        """Normalize text and map element IDs to code-point offsets in that text."""
        raw = "".join(self.parts)
        pending = sorted(
            (offset, name)
            for name, offset in self.anchors.items()
            if offset is not None
        )
        anchors: dict[str, int | None] = dict.fromkeys(self.anchors)
        lines: list[str] = []
        raw_position = 0
        output_position = 0
        anchor_index = 0
        for line in raw.splitlines(keepends=True):
            trimmed = line.strip()
            if trimmed:
                text_start = raw_position + len(line) - len(line.lstrip())
                text_end = text_start + len(trimmed)
                if lines:
                    output_position += 1
                while (
                    anchor_index < len(pending) and pending[anchor_index][0] < text_end
                ):
                    raw_offset, name = pending[anchor_index]
                    anchors[name] = output_position + max(0, raw_offset - text_start)
                    anchor_index += 1
                lines.append(trimmed)
                output_position += len(trimmed)
            raw_position += len(line)
        return "\n".join(lines), anchors


def _xml(archive: ZipFile, name: str):
    return ElementTree.fromstring(archive.read(name))


def _resolve(base: str, href: str) -> str:
    url = urlsplit(href)
    if url.scheme or url.netloc or url.query or url.fragment:
        raise InvalidEpub("Unsupported EPUB resource path.")
    path = PurePosixPath(unquote(url.path))
    if path.is_absolute() or ".." in path.parts or "\\" in str(path):
        raise InvalidEpub("Unsafe EPUB resource path.")
    return str(PurePosixPath(base).parent / path)


def _navigation_target(base: str, href: str) -> tuple[str, str] | None:
    url = urlsplit(href)
    if url.scheme or url.netloc or url.query:
        return None
    path = unquote(url.path)
    if path.startswith("/") or "\\" in path:
        return None
    resolved = normpath(join(dirname(base), path)) if path else base
    if resolved == ".." or resolved.startswith("../"):
        return None
    return resolved, unquote(url.fragment)


def _navigation(
    archive: ZipFile, package_path: str, package, manifest, locations
) -> tuple[NavigationEntry, ...]:
    """Extract TOC links as suggestions, never as confirmed chapter boundaries."""
    nav_item = next(
        (
            item
            for item in manifest.values()
            if "nav" in item.get("properties", "").split()
        ),
        None,
    )
    spine = package.find("./{*}spine")
    ncx_item = manifest.get(spine.get("toc")) if spine is not None else None
    source = nav_item if nav_item is not None else ncx_item
    if source is None or not source.get("href"):
        return ()
    try:
        nav_path = _resolve(package_path, source.attrib["href"])
        root = _xml(archive, nav_path)
        if nav_item is not None:
            toc = next(
                (
                    node
                    for node in root.iter()
                    if node.tag.rsplit("}", 1)[-1] == "nav"
                    and "toc"
                    in node.get("{http://www.idpf.org/2007/ops}type", "").split()
                ),
                None,
            )
            links = (
                []
                if toc is None
                else [
                    ("".join(node.itertext()).strip(), node.get("href"))
                    for node in toc.iter()
                    if node.tag.rsplit("}", 1)[-1] == "a"
                ]
            )
        else:
            links = []
            for point in root.findall(".//{*}navMap//{*}navPoint"):
                label = point.find("./{*}navLabel/{*}text")
                content = point.find("./{*}content")
                links.append(
                    (
                        "".join(label.itertext()).strip() if label is not None else "",
                        content.get("src") if content is not None else None,
                    )
                )
        result = []
        for title, href in links:
            target = _navigation_target(nav_path, href) if href else None
            position = None
            offset = None
            if target and target[0] in locations:
                location = locations[target[0]]
                if location is not None:
                    position, anchors = location
                    offset = anchors.get(target[1]) if target[1] else 0
                    if offset is None:
                        position = None
            result.append(NavigationEntry(title, position, offset))
        return tuple(result)
    except (KeyError, ValueError, DefusedXmlException, ParseError, InvalidEpub):
        return ()


def read_epub(data: bytes) -> Book:
    """Parse a bounded EPUB without treating its spine items as confirmed chapters."""
    if len(data) > MAX_ARCHIVE_BYTES:
        raise InvalidEpub("EPUB exceeds the 25 MB upload limit.")
    try:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if (
                len(entries) > MAX_ENTRIES
                or sum(e.file_size for e in entries) > MAX_UNPACKED_BYTES
            ):
                raise InvalidEpub("EPUB contents exceed import limits.")
            if len(names) != len(set(names)):
                raise InvalidEpub("EPUB contains duplicate paths.")
            if (
                any(entry.flag_bits & 1 for entry in entries)
                or "META-INF/encryption.xml" in names
            ):
                raise InvalidEpub("Encrypted or protected EPUBs are not supported.")
            if archive.read("mimetype") != b"application/epub+zip":
                raise InvalidEpub("This file is not an EPUB.")
            container = _xml(archive, "META-INF/container.xml")
            rootfile = container.find(".//{*}rootfile")
            if rootfile is None or not rootfile.get("full-path"):
                raise InvalidEpub("EPUB package is missing.")
            package_path = _resolve("root", rootfile.attrib["full-path"])
            package = _xml(archive, package_path)
            title_element = package.find("./{*}metadata/{*}title")
            title = (
                "".join(title_element.itertext()).strip()
                if title_element is not None
                else ""
            )
            manifest = {
                item.get("id"): item
                for item in package.findall("./{*}manifest/{*}item")
                if item.get("id")
            }
            sections = []
            locations = {}
            for ref in package.findall("./{*}spine/{*}itemref"):
                if ref.get("linear", "yes") == "no":
                    continue
                item = manifest.get(ref.get("idref"))
                if item is None or not item.get("href"):
                    raise InvalidEpub("EPUB reading order references a missing item.")
                if item.get("media-type") not in {"application/xhtml+xml", "text/html"}:
                    raise InvalidEpub(
                        "EPUB has unsupported content in its reading order."
                    )
                path = _resolve(package_path, item.attrib["href"])
                content = archive.read(path)
                parser = TextExtractor()
                parser.feed(content.decode("utf-8-sig"))
                text, anchors = parser.extract()
                if text:
                    if path in locations:
                        locations[path] = None
                    else:
                        locations[path] = (len(sections), anchors)
                    sections.append(Section(text=text))
            if not sections:
                raise InvalidEpub("EPUB has no readable text in its reading order.")
            navigation = _navigation(
                archive, package_path, package, manifest, locations
            )
            return Book(
                title=title or "Untitled book",
                sections=tuple(sections),
                navigation=navigation,
            )
    except InvalidEpub:
        raise
    except (
        BadZipFile,
        KeyError,
        ValueError,
        UnicodeError,
        DefusedXmlException,
        RuntimeError,
        ParseError,
    ) as exc:
        raise InvalidEpub(
            "The EPUB is malformed or uses an unsupported format."
        ) from exc
