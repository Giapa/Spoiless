import json
import os
import subprocess
import sys
from pathlib import Path

from scripts.evaluate_retrieval import CHAPTERS, _safe_results, sample_epub
from spoiless.epub import read_epub
from spoiless.retrieval.search import Passage


def test_sample_epub_and_independent_boundary_check():
    book = read_epub(sample_epub())
    sample_path = (
        Path(__file__).resolve().parents[1] / "examples" / "the-inland-compass.epub"
    )
    assert read_epub(sample_path.read_bytes()) == book
    assert len(book.navigation) == 6
    assert book.navigation[1].character_offset == len(CHAPTERS[0]) + 1
    assert _safe_results([Passage(0, 0, CHAPTERS[0] + "\n")], 2)
    assert not _safe_results([Passage(0, 0, CHAPTERS[0] + "\n" + CHAPTERS[1])], 2)
    assert not _safe_results([Passage(1, 0, CHAPTERS[2])], 2)


def test_evaluation_runs_offline_and_leaves_library_alone(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "evaluate_retrieval.py"
    data_home = tmp_path / "user-data"
    data_home.mkdir()
    sentinel = data_home / "keep.txt"
    sentinel.write_text("unchanged")
    env = {**os.environ, "XDG_DATA_HOME": str(data_home), "HF_HUB_OFFLINE": "1"}
    result = subprocess.run(
        [sys.executable, str(script)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    output = json.loads(result.stdout)
    assert output["keyword"]["boundary_checks"] == 24
    assert output["keyword"]["boundary_violations"] == 0
    assert output["hybrid"] is None
    assert list(data_home.iterdir()) == [sentinel]
    assert sentinel.read_text() == "unchanged"
    missing_model = subprocess.run(
        [sys.executable, str(script), "--hybrid"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert missing_model.returncode == 2
    assert "Download model" in missing_model.stderr
    assert list(data_home.iterdir()) == [sentinel]
