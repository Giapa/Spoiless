from io import BytesIO
from zipfile import ZipFile

import pytest

from spoiless.epub import InvalidEpub, read_epub


def epub(*, href: str = "one.xhtml", extra: dict[str, str] | None = None) -> bytes:
    files = {
        "mimetype": "application/epub+zip",
        "META-INF/container.xml": (
            '<container><rootfiles><rootfile full-path="book/content.opf"/>'
            "</rootfiles></container>"
        ),
        "book/content.opf": f'''<package xmlns:dc="http://purl.org/dc/elements/1.1/">
            <metadata><dc:title>A Book</dc:title></metadata>
            <manifest><item id="one" href="{href}" media-type="application/xhtml+xml"/>
              <item id="two" href="two.xhtml"
                media-type="application/xhtml+xml"/></manifest>
            <spine><itemref idref="two"/><itemref idref="one"/></spine></package>''',
        "book/one.xhtml": (
            "<html><body><h1>First</h1><p>A &amp; B</p>"
            "<script>hidden</script></body></html>"
        ),
        "book/two.xhtml": "<html><body><p>Second section</p></body></html>",
    }
    files.update(extra or {})
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return output.getvalue()


def test_reads_spine_order_without_claiming_chapter_boundaries() -> None:
    book = read_epub(epub())
    assert book.title == "A Book"
    assert [section.text for section in book.sections] == [
        "Second section",
        "First\nA & B",
    ]


@pytest.mark.parametrize(
    "data",
    [
        b"not a zip",
        epub(href="../escape.xhtml"),
        epub(extra={"META-INF/encryption.xml": "<encryption/>"}),
        epub(extra={"META-INF/container.xml": "<broken"}),
        epub(extra={"book/content.opf": '<!DOCTYPE a [<!ENTITY x "x">]><a>&x;</a>'}),
    ],
)
def test_rejects_unsupported_or_unsafe_files(data: bytes) -> None:
    with pytest.raises(InvalidEpub):
        read_epub(data)
