from copy import deepcopy

import pytest

from gorak import native_styles
from gorak.style_values import merge


def test_nested_merge_preserves_order_and_owns_all_mutable_branches() -> None:
    shared = {"items": [1, 2], "label": "old"}
    parent = {"first": shared, "second": shared, "removed": 3}
    overrides = {
        "first": {"label": "new", "added": {"items": [4]}},
        "removed": None,
        "last": [5],
        "$before": {"last": "second"},
    }
    originals = deepcopy((parent, overrides))
    result = merge(parent, overrides)
    assert list(result) == ["first", "last", "second"]
    assert result == {
        "first": {"items": [1, 2], "label": "new", "added": {"items": [4]}},
        "last": [5],
        "second": {"items": [1, 2], "label": "old"},
    }
    result["first"]["items"].append(9)
    result["first"]["added"]["items"].append(9)
    result["last"].append(9)
    assert result["second"]["items"] == [1, 2]
    result["second"]["items"].append(8)
    assert (parent, overrides) == originals


def test_nested_merge_replaces_scalar_with_object_and_respects_explicit_order() -> None:
    parent = {"one": 1, "two": {"a": 1, "b": 2}}
    result = merge(
        parent,
        {"one": {"value": [3]}, "two": {"a": None, "c": 4, "$order": ["c", "b"]}},
    )
    assert result == {"one": {"value": [3]}, "two": {"c": 4, "b": 2}}
    assert list(result["two"]) == ["c", "b"]
    assert parent == {"one": 1, "two": {"a": 1, "b": 2}}


def test_packaged_baseline_is_independent_between_callers() -> None:
    expected = native_styles.baseline()
    first = native_styles.baseline()
    first["groups"].clear()
    first["group_order"].clear()
    assert native_styles.baseline() == expected


def test_identical_validated_styles_need_no_recursive_difference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = native_styles.baseline()
    monkeypatch.setattr(
        native_styles,
        "property_difference",
        lambda *args: pytest.fail("identical styles traversed again"),
    )
    with native_styles.validation_scope():
        assert native_styles.difference(parent, deepcopy(parent)) == {}


def test_identical_invalid_styles_are_still_rejected() -> None:
    from gorak.errors import ProjectError

    with native_styles.validation_scope(), pytest.raises(ProjectError):
        native_styles.difference({"invalid": "value"}, {"invalid": "value"})
