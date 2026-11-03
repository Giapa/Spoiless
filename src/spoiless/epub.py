"""Read EPUB content as unconfirmed, ordered spine sections."""

from dataclasses import dataclass
from html.parser import HTMLParser
from io import BytesIO
from pathlib import PurePosixPath
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
class Book:
    title: str
    sections: tuple[Section, ...]


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

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
            self.parts.append("\n")

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
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


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
                content = archive.read(_resolve(package_path, item.attrib["href"]))
                parser = TextExtractor()
                parser.feed(content.decode("utf-8-sig"))
                text = "\n".join(
                    line.strip()
                    for line in "".join(parser.parts).splitlines()
                    if line.strip()
                )
                if text:
                    sections.append(Section(text=text))
            if not sections:
                raise InvalidEpub("EPUB has no readable text in its reading order.")
            return Book(title=title or "Untitled book", sections=tuple(sections))
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
