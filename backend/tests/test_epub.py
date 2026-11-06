from io import BytesIO
from zipfile import ZipFile

import pytest

from src.library.epub import InvalidEpub, NavigationEntry, read_epub


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


def test_epub3_navigation_resolves_anchors_in_normalized_text() -> None:
    package = """<package xmlns:dc="http://purl.org/dc/elements/1.1/">
        <metadata><dc:title>Book</dc:title></metadata>
        <manifest><item id="nav" href="navigation/toc.xhtml" properties="nav"
             media-type="application/xhtml+xml"/>
          <item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>
        </manifest>
        <spine><itemref idref="one"/></spine></package>"""
    nav = """<html xmlns:epub="http://www.idpf.org/2007/ops"><body>
        <nav epub:type="toc"><ol>
          <li><a href="../one.xhtml#begin">Chapter 1</a></li>
          <li><a href="../one.xhtml#later">Chapter 2</a></li>
          <li><a href="../one.xhtml#missing">Unknown</a></li>
          <li><a href="https://example.com/">External</a></li>
        </ol></nav></body></html>"""
    text = '<body><p id="begin"> Intro 📚 </p>\n<h2 id="later"> Next </h2></body>'
    book = read_epub(
        epub(
            extra={
                "book/content.opf": package,
                "book/navigation/toc.xhtml": nav,
                "book/one.xhtml": text,
            }
        )
    )
    assert book.sections[0].text == "Intro 📚\nNext"
    assert book.navigation == (
        NavigationEntry("Chapter 1", 0, 0),
        NavigationEntry("Chapter 2", 0, 8),
        NavigationEntry("Unknown", None, None),
        NavigationEntry("External", None, None),
    )


def test_epub2_ncx_navigation_and_ambiguous_fragment() -> None:
    package = """<package><metadata><title>Book</title></metadata><manifest>
        <item id="toc" href="toc.ncx" media-type="application/x-dtbncx+xml"/>
        <item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>
        </manifest><spine toc="toc"><itemref idref="one"/></spine></package>"""
    ncx = """<ncx><navMap><navPoint><navLabel><text>First</text></navLabel>
        <content src="one.xhtml#repeat"/></navPoint><navPoint>
        <navLabel><text>Second</text></navLabel><content src="one.xhtml"/>
        </navPoint></navMap></ncx>"""
    text = '<body><p id="repeat">One</p><p id="repeat">Two</p></body>'
    book = read_epub(
        epub(
            extra={
                "book/content.opf": package,
                "book/toc.ncx": ncx,
                "book/one.xhtml": text,
            }
        )
    )
    assert book.navigation == (
        NavigationEntry("First", None, None),
        NavigationEntry("Second", 0, 0),
    )


def test_missing_or_invalid_navigation_does_not_confirm_or_reject_book() -> None:
    assert read_epub(epub()).navigation == ()
    package = """<package><manifest>
        <item id="nav" href="toc.xhtml" properties="nav"
            media-type="application/xhtml+xml"/>
        <item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>
        </manifest><spine><itemref idref="one"/></spine></package>"""
    book = read_epub(
        epub(extra={"book/content.opf": package, "book/toc.xhtml": "<broken"})
    )
    assert book.sections and book.navigation == ()


def test_document_head_is_not_in_book_passages() -> None:
    book = read_epub(
        epub(
            extra={
                "book/two.xhtml": (
                    "<html><head><title>Hidden document title</title>"
                    "<style>.x{color:red}</style></head>"
                    "<body><p>Visible chapter</p></body></html>"
                )
            }
        )
    )
    assert book.sections[0].text == "Visible chapter"


def test_detects_chapters_from_nested_navigation_and_headings():
    package = """<package><manifest>
      <item id="nav" href="toc.xhtml" properties="nav"
        media-type="application/xhtml+xml"/>
      <item id="front" href="front.xhtml" media-type="application/xhtml+xml"/>
      <item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>
      </manifest><spine><itemref idref="front"/><itemref idref="one"/>
      </spine></package>"""
    nav = """<html xmlns:epub="http://www.idpf.org/2007/ops"><body>
      <nav epub:type="toc"><ol><li><a href="front.xhtml">Introduction</a></li>
      <li><a href="one.xhtml">Part One</a><ol>
      <li><a href="one.xhtml#one">Chapter 1</a></li>
      <li><a href="one.xhtml#two">Chapter 2</a></li></ol></li>
      </ol></nav></body></html>"""
    book = read_epub(
        epub(
            extra={
                "book/content.opf": package,
                "book/toc.xhtml": nav,
                "book/front.xhtml": "<h1>Introduction</h1><p>Front</p>",
                "book/one.xhtml": '<h1 id="one">Chapter 1</h1><p>Read</p>'
                '<h1 id="two">Chapter 2</h1><p>Unread</p>',
            }
        )
    )
    assert book.chapters == ((1, 0), (1, book.sections[1].text.index("Chapter 2")))


def test_missing_navigation_detects_chapter_headings_or_uses_one_chapter():
    book = read_epub(
        epub(
            extra={
                "book/two.xhtml": "<h1>Preface</h1><p>Intro</p>",
                "book/one.xhtml": "<h1>Chapter 1</h1><p>Read</p>"
                "<h1>Chapter 2</h1><p>Unread</p>",
            }
        )
    )
    assert book.chapters == ((1, 0), (1, book.sections[1].text.index("Chapter 2")))
    assert read_epub(epub()).chapters == ()


def test_uncertain_chapter_boundaries_fail_closed():
    book = read_epub(
        epub(
            extra={
                "book/two.xhtml": "<h1>Preface</h1>",
                "book/one.xhtml": "<h1>Chapter 1</h1><p>One</p>"
                "<h1>Lost chapter</h1><p>Two</p>"
                "<h1>Chapter 3</h1><p>Three</p>",
            }
        )
    )
    assert book.chapters == ()
    gap = read_epub(
        epub(
            extra={
                "book/two.xhtml": "<h1>Preface</h1>",
                "book/one.xhtml": "<h1>Chapter 1</h1><p>One</p>"
                "<h1>Chapter 3</h1><p>Three</p>",
            }
        )
    )
    assert gap.chapters == ()
    roman = read_epub(
        epub(
            extra={
                "book/two.xhtml": "<h1>Preface</h1>",
                "book/one.xhtml": "<h1>Chapter I</h1><p>One</p>"
                "<h1>Chapter III</h1><p>Three</p>",
            }
        )
    )
    assert roman.chapters == ()


def test_unclassified_navigation_might_hide_a_chapter():
    from src.library.epub import Section, _chapters

    sections = (Section("Chapter 1\nRead\nAn untitled chapter\nUnread"),)
    headings = ((0, 0, False),)
    chapter = NavigationEntry("Chapter 1", 0, 0)
    assert _chapters(sections, (chapter,), headings) == ((0, 0),)
    assert (
        _chapters(sections, (chapter, NavigationEntry("Untitled", 0, 15)), headings)
        == ()
    )
    assert (
        _chapters(
            sections, (chapter, NavigationEntry("Untitled", None, None)), headings
        )
        == ()
    )


def test_detected_chapter_heading_is_available_as_title_without_navigation():
    book = read_epub(
        epub(
            extra={
                "book/two.xhtml": "<h1>Preface</h1>",
                "book/one.xhtml": "<h1>Chapter 1</h1><p>Read</p>"
                "<h1>Chapter 2</h1><p>Unread</p>",
            }
        )
    )
    assert book.navigation == (
        NavigationEntry("Chapter 1", 1, 0),
        NavigationEntry("Chapter 2", 1, book.sections[1].text.index("Chapter 2")),
    )


def test_unexplained_spine_section_cannot_be_absorbed_into_a_chapter():
    package = """<package><manifest>
      <item id="front" href="front.xhtml" media-type="application/xhtml+xml"/>
      <item id="one" href="one.xhtml" media-type="application/xhtml+xml"/>
      <item id="middle" href="middle.xhtml" media-type="application/xhtml+xml"/>
      <item id="two" href="two.xhtml" media-type="application/xhtml+xml"/>
      </manifest><spine><itemref idref="front"/><itemref idref="one"/>
      <itemref idref="middle"/><itemref idref="two"/></spine></package>"""
    files = {
        "book/content.opf": package,
        "book/front.xhtml": "<h1>Preface</h1><p>Introduction</p>",
        "book/one.xhtml": "<h1>Chapter 1</h1><p>Read</p>",
        "book/two.xhtml": "<h1>Chapter 2</h1><p>Later</p>",
    }
    # An unmarked chapter and a continuation are indistinguishable here.
    for middle in ("<p>Unread chapter</p>", "<p>Chapter 1 continued</p>"):
        book = read_epub(epub(extra={**files, "book/middle.xhtml": middle}))
        assert book.chapters == ()

    # Front matter and chapters in separate files remain supported.
    book = read_epub(
        epub(
            extra={
                **files,
                "book/middle.xhtml": "<h1>Chapter 2</h1><p>Read</p>",
                "book/two.xhtml": "<h1>Chapter 3</h1><p>Later</p>",
            }
        )
    )
    assert book.chapters == ((1, 0), (2, 0), (3, 0))
