"""Offline retrieval evaluation using an original, redistributable short story."""

import argparse
import html
import json
import os
import statistics
import sys
import tempfile
import time
from io import BytesIO
from unittest.mock import patch
from zipfile import ZIP_STORED, ZipFile

from spoiless.library import storage as library
from spoiless.library.epub import read_epub
from spoiless.retrieval import embedding_model
from spoiless.retrieval import search as retrieval

# Original text written for this project, released under CC0-1.0.
CHAPTERS = (
    "Mara, the lighthouse keeper, found a brass compass beneath the stairs. "
    "Its needle pointed inland instead of toward the sea.",
    "At the bakery, Ivo traded Mara a map for a jar of honey. "
    "The map showed a path through the abandoned orchard.",
    "A storm flooded the bridge. Mara and Ivo crossed the river in a red boat "
    "borrowed from their neighbour Leda.",
    "Inside the orchard they found a locked wooden chest. The key was hidden "
    "inside the hollow trunk of an old pear tree.",
    "The chest contained a faded letter from Mara's mother, revealing that "
    "Leda was her aunt. Ivo promised to keep the discovery private.",
    "At dawn, Mara returned the compass to Leda. Together they lit the "
    "lighthouse to guide a lost ship safely into harbour.",
)
# Gold evidence is an exact substring from the source, not a model-generated answer.
QUESTIONS = (
    ("What brass object did Mara find?", "brass compass"),
    ("What did Ivo receive for the map?", "jar of honey"),
    ("How did they travel over the flooded water?", "red boat"),
    ("Where was the chest key concealed?", "hollow trunk"),
    ("How is Leda related to Mara?", "her aunt"),
    ("What did they light to guide the vessel?", "lit the lighthouse"),
)


def sample_epub() -> bytes:
    """Make an EPUB with two chapters in one spine document."""
    manifest = "".join(
        f'<item id="s{i}" href="s{i}.xhtml" media-type="application/xhtml+xml"/>'
        for i in range(5)
    )
    spine = "".join(f'<itemref idref="s{i}"/>' for i in range(5))
    sections = (CHAPTERS[0] + "\n" + CHAPTERS[1], *CHAPTERS[2:])
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
            'version="1.0"><rootfiles><rootfile full-path="book.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        archive.writestr(
            "book.opf",
            '<package xmlns="http://www.idpf.org/2007/opf" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" version="3.0" '
            'unique-identifier="book-id"><metadata>'
            '<dc:identifier id="book-id">urn:uuid:'
            "8c7a98f2-01a5-48ac-a95d-1059e6b4f97e</dc:identifier>"
            "<dc:title>The Inland Compass</dc:title><dc:language>en</dc:language>"
            '<meta property="dcterms:modified">2026-01-01T00:00:00Z</meta></metadata>'
            f'<manifest>{manifest}<item id="nav" href="nav.xhtml" properties="nav" '
            'media-type="application/xhtml+xml"/></manifest>'
            f"<spine>{spine}</spine></package>",
        )
        links = []
        for chapter in range(6):
            section_index = max(0, chapter - 1)
            links.append(
                f'<li><a href="s{section_index}.xhtml#c{chapter + 1}">'
                f"Chapter {chapter + 1}</a></li>"
            )
        archive.writestr(
            "nav.xhtml",
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" lang="en">'
            '<head><title>Contents</title></head><body><nav epub:type="toc">'
            f"<h1>Contents</h1><ol>{''.join(links)}</ol></nav></body></html>",
        )
        for index, section in enumerate(sections):
            paragraphs = "".join(
                f'<p id="c{part + 1 if index == 0 else index + 2}">'
                f"{html.escape(line)}</p>"
                for part, line in enumerate(section.split("\n"))
            )
            archive.writestr(
                f"s{index}.xhtml",
                '<html xmlns="http://www.w3.org/1999/xhtml" lang="en">'
                f"<head><title>Section {index + 1}</title></head>"
                f"<body>{paragraphs}</body></html>",
            )
    return output.getvalue()


def _allowed_sections(current: int) -> dict[int, str]:
    """Ground truth independently constructed from the authored chapter text."""
    completed = current - 1
    # The newline separating chapters belongs before chapter 2's start offset.
    first = CHAPTERS[0] + "\n"
    if completed >= 2:
        first += CHAPTERS[1]
    allowed = {0: first}
    for chapter in range(2, completed):
        allowed[chapter - 1] = CHAPTERS[chapter]
    return allowed


def _safe_results(results: list[retrieval.Passage], current: int) -> bool:
    allowed = _allowed_sections(current)
    for passage in results:
        source = allowed.get(passage.section_position)
        if source is None or passage.character_offset < 0:
            return False
        offset = passage.character_offset
        if (
            not passage.text
            or source[offset : offset + len(passage.text)] != passage.text
        ):
            return False
    return True


def evaluate(search, book_id: str) -> dict:
    library.set_progress(book_id, 7)  # All six chapters are complete.
    ranks = []
    timings = []
    cpu_start = time.process_time()
    for question, evidence in QUESTIONS:
        start = time.perf_counter()
        results = search(book_id, question, limit=5)
        timings.append(time.perf_counter() - start)
        if not _safe_results(results, 7):
            raise AssertionError("A result was outside the original source text.")
        rank = next(
            (i for i, result in enumerate(results, 1) if evidence in result.text), None
        )
        ranks.append(rank)
    start = time.perf_counter()
    warm_results = search(book_id, QUESTIONS[0][0], limit=5)
    warm_seconds = time.perf_counter() - start
    if not _safe_results(warm_results, 7):
        raise AssertionError("A warm search returned invalid source text.")
    cpu_seconds = time.process_time() - cpu_start
    checks = 0
    violations = 0
    for current in (2, 3, 4, 6):
        library.set_progress(book_id, current)
        for question in (
            "compass",
            "honey",
            "red boat",
            "hollow trunk",
            "aunt",
            "lighthouse",
        ):
            results = search(book_id, question, limit=5)
            checks += 1
            violations += not _safe_results(results, current)
    count = len(QUESTIONS)
    return {
        "questions": count,
        "recall_at_1": sum(rank == 1 for rank in ranks) / count,
        "recall_at_3": sum(rank is not None and rank <= 3 for rank in ranks) / count,
        "mrr_at_5": sum(1 / rank if rank is not None else 0 for rank in ranks) / count,
        "ranks": ranks,
        "boundary_checks": checks,
        "boundary_violations": violations,
        "first_query_wall_seconds": round(timings[0], 4),
        "median_query_wall_seconds": round(statistics.median(timings), 4),
        "repeat_query_wall_seconds": round(warm_seconds, 4),
        "quality_queries_cpu_seconds": round(cpu_seconds, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hybrid",
        action="store_true",
        help="also evaluate an already downloaded model",
    )
    args = parser.parse_args()
    # Capture the real local model before pointing the library at temporary data.
    model_directory = embedding_model.model_dir()
    if args.hybrid and not embedding_model.model_ready():
        print(
            "Model not downloaded. Use the app's Download model action first.",
            file=sys.stderr,
        )
        return 2
    old_data_home = os.environ.get("XDG_DATA_HOME")
    try:
        with tempfile.TemporaryDirectory(prefix="spoiless-eval-") as directory:
            os.environ["XDG_DATA_HOME"] = directory
            with patch.object(
                embedding_model, "model_dir", return_value=model_directory
            ):
                parsed = read_epub(sample_epub())
                sections = [section.text for section in parsed.sections]
                expected = [CHAPTERS[0] + "\n" + CHAPTERS[1], *CHAPTERS[2:]]
                if sections != expected:
                    raise AssertionError("EPUB text did not match the source story.")
                book_id = library.add_book(parsed)
                units = [
                    library.ReadingUnitStart("chapter", 0, 0),
                    library.ReadingUnitStart("chapter", 0, len(CHAPTERS[0]) + 1),
                    *(library.ReadingUnitStart("chapter", i, 0) for i in range(1, 5)),
                ]
                library.confirm_reading_units(book_id, units)
                output = {
                    "fixture": "The Inland Compass (original synthetic text, CC0-1.0)",
                    "scope": "6 authored questions; not a representative benchmark",
                    "keyword": evaluate(retrieval.keyword_search, book_id),
                    "hybrid": None,
                }
                if args.hybrid:
                    try:
                        output["hybrid"] = evaluate(retrieval.hybrid_search, book_id)
                    except retrieval.ModelUnavailable:
                        print(
                            "The cached model could not be loaded. Check its setup.",
                            file=sys.stderr,
                        )
                        return 2
                print(json.dumps(output, indent=2))
    finally:
        if old_data_home is None:
            os.environ.pop("XDG_DATA_HOME", None)
        else:
            os.environ["XDG_DATA_HOME"] = old_data_home
    return (
        1
        if any(
            result and result["boundary_violations"]
            for result in (output["keyword"], output["hybrid"])
        )
        else 0
    )


if __name__ == "__main__":
    sys.exit(main())
