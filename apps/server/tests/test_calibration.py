"""The parts of `scripts/calibrate_costs.py` that can be wrong quietly.

Most of that script is a running stack away from being testable, but the fit is
not: it is the thing that turns a corpus into the numbers `credits.md` will be
rewritten from, and a fit that is subtly wrong produces a plausible answer
rather than an obvious failure.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

from calibrate_costs import fit, read_corpus  # noqa: E402


def test_the_fit_recovers_a_line_it_was_given() -> None:
    """0.6 tokens per character over a 2,000-token preamble — the shape
    `credits.md` assumes, planted so the fit has a known answer to find."""
    points = [(chars, 0.6 * chars + 2_000) for chars in (1_000, 5_000, 20_000, 300_000)]

    fitted = fit(points)

    assert fitted is not None
    slope, intercept = fitted
    assert round(slope, 6) == 0.6
    assert round(intercept) == 2_000


def test_a_corpus_at_one_length_fixes_nothing() -> None:
    """Points clustered at a single length fix a slope no better than one point.

    This is the failure mode a corpus invites: it is much easier to gather ten
    articles of similar size than a spread, and the result looks like a
    measurement rather than the refusal it should be.
    """
    assert fit([(5_000, 5_000.0), (5_000, 5_100.0), (5_000, 4_900.0)]) is None


def test_too_few_points_are_refused_rather_than_extrapolated() -> None:
    assert fit([(1_000, 2_600.0), (5_000, 5_000.0)]) is None


def test_a_corpus_is_the_text_files_in_it_and_nothing_else(tmp_path: Path) -> None:
    (tmp_path / "long.txt").write_text("四天工作制的真实成本" * 50, encoding="utf-8")
    (tmp_path / "short.md").write_text("远程办公的生产力争论", encoding="utf-8")
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")
    (tmp_path / "blank.txt").write_text("   \n ", encoding="utf-8")
    (tmp_path / "nested").mkdir()

    pieces = read_corpus(tmp_path)

    assert [piece.name for piece in pieces] == ["long.txt", "short.md"]
    assert [piece.characters for piece in pieces] == [500, 10]
