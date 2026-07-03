"""Unit tests for the AMPL ``.dat`` subset parser (S2c)."""

import pytest

from app.domains.dsl import JModelError
from app.domains.dsl.dat_parser import parse_dat

GOLDEN = """
# knapsack scenario
set I := a b c;
param cap := 10;
param w := a 2, b 3, c 4;
param cost := a p 1, a q 2, b p 3, b q 4;  # 2-D
"""


def test_golden_dat_parses_to_dataset_shape():
    data = parse_dat(GOLDEN)
    assert data == {
        "sets": {"I": ["a", "b", "c"]},
        "params": {
            "cap": 10.0,
            "w": {"a": 2.0, "b": 3.0, "c": 4.0},
            "cost": {"a,p": 1.0, "a,q": 2.0, "b,p": 3.0, "b,q": 4.0},
        },
    }


def test_set_members_allow_commas():
    assert parse_dat("set I := a, b, c;") == {"sets": {"I": ["a", "b", "c"]}, "params": {}}


def test_scientific_notation_and_negatives():
    data = parse_dat("param w := a 1e-3, b -2.5;")
    assert data["params"]["w"] == {"a": 0.001, "b": -2.5}


@pytest.mark.parametrize(
    ("src", "pattern"),
    [
        ("set I := a b c", "expected a member or ';'"),  # missing ';' hits EOF
        ("set I := ;", "has no members"),
        ("param w := a 2, b 3, c;", "must end in a number"),
        ("param w := a 2, b p 3;", "disagree on arity"),
        ("param w := a 2, a 3;", "duplicate key"),
        ("param w := 1, 2;", "mixes a scalar"),
        ("set I := a; set I := b;", "duplicate symbol"),
        ("bogus I := a;", "expected 'set' or 'param'"),
        ("param w := a 2,, b 3;", "empty entry"),
    ],
)
def test_errors_are_jmodel_errors(src: str, pattern: str):
    with pytest.raises(JModelError, match=pattern):
        parse_dat(src)


def test_error_position_points_into_the_source():
    src = "set I := a b c;\nparam w := a x;"
    with pytest.raises(JModelError) as exc_info:
        parse_dat(src)
    assert exc_info.value.position == src.index("x")


def test_illegal_character_rejected():
    with pytest.raises(JModelError, match="illegal character"):
        parse_dat("set I := a { b;")
