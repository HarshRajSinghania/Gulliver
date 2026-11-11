import pytest

from gulliver.checks import parse_spec


def _bounds(text):
    return parse_spec(ranges=[f"amount={text}"]).ranges["amount"]


@pytest.mark.parametrize("text", ["nan:", ":inf", "-inf:", ":nan"])
def test_range_refuses_non_finite_bounds(text):
    with pytest.raises(ValueError, match="finite"):
        parse_spec(ranges=[f"amount={text}"])


def test_range_refuses_a_non_number():
    with pytest.raises(ValueError, match=r"range for 'amount' needs numbers, got 'abc'"):
        parse_spec(ranges=["amount=abc:1"])


def test_range_refuses_inverted_bounds():
    with pytest.raises(ValueError, match=r"range for 'amount' has min 100 > max 1"):
        parse_spec(ranges=["amount=100:1"])


def test_range_bounds_still_parse():
    assert _bounds("0:") == (0.0, None)
    assert _bounds(":10") == (None, 10.0)
    assert _bounds("5:5") == (5.0, 5.0)



def test_merge_specs():
    from gulliver.checks import CheckSpec, merge_specs

    base = CheckSpec(
        unique=[["id"]],
        not_null=["user_id"],
        accepted={"status": ["active"]},
        ranges={"amount": (0.0, 100.0)},
        fresh={"ts": "24h"},
        min_rows=100,
        max_change_pct=10.0,
    )
    override = CheckSpec(
        unique=[["id"], ["email", "domain"]],
        not_null=["user_id", "email"],
        accepted={"status": ["active", "pending"], "type": ["a", "b"]},
        ranges={"amount": (10.0, 50.0), "score": (0.0, 1.0)},
        fresh={"ts": "12h", "created_at": "1h"},
        min_rows=500,
        max_change_pct=5.0,
    )
    merged = merge_specs(base, override)
    assert merged.unique == [["id"], ["email", "domain"]]
    assert merged.not_null == ["user_id", "email"]
    assert merged.accepted == {"status": ["active", "pending"], "type": ["a", "b"]}
    assert merged.ranges == {"amount": (10.0, 50.0), "score": (0.0, 1.0)}
    assert merged.fresh == {"ts": "12h", "created_at": "1h"}
    assert merged.min_rows == 500
    assert merged.max_change_pct == 5.0

    # Merging with empty override preserves base values
    empty_override = CheckSpec()
    merged_preserve = merge_specs(base, empty_override)
    assert merged_preserve.unique == [["id"]]
    assert merged_preserve.not_null == ["user_id"]
    assert merged_preserve.min_rows == 100
    assert merged_preserve.max_change_pct == 10.0
