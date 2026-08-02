"""Synthesis strips ```recommendation JSON into structured state."""

from mas_sector_system.agents import _split_recommendation_block


def test_split_recommendation_block():
    raw = """# Memo

## Recommendation
HOLD.

```recommendation
{"rating": "HOLD", "preferred_lens": "comps", "override_reason": "DCF diagnostic", "primary_method_direction": "overvalued"}
```
"""
    memo, rec = _split_recommendation_block(raw)
    assert "HOLD" in memo
    assert "```recommendation" not in memo
    assert rec is not None
    assert rec["rating"] == "HOLD"
    assert rec["preferred_lens"] == "comps"


def test_no_block_returns_none():
    memo, rec = _split_recommendation_block("Just a memo.\n")
    assert memo == "Just a memo.\n"
    assert rec is None
