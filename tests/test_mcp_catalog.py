"""Curated MCP catalog tests: file data only, no network."""

import pytest

from mcp.catalog import (
    CALL_STYLE_FLAT,
    CALL_STYLE_PARAMS,
    MAX_TOOLS,
    MIN_TOOLS,
    all_tools,
    call_style,
    is_allowed,
    role_of,
    tools_for,
    validate_catalog,
)


def test_catalog_loads_with_both_roles():
    assert set(tools_for("operator"))  # non-empty
    assert set(tools_for("technician"))  # non-empty
    assert len(all_tools()) == len(tools_for("operator")) + len(
        tools_for("technician")
    )


def test_count_stays_within_bounds():
    count = validate_catalog()
    assert MIN_TOOLS <= count <= MAX_TOOLS


def test_every_listed_tool_passes_validation():
    for name in all_tools():
        assert is_allowed(name) is True
        assert role_of(name) in ("operator", "technician")
        assert call_style(name) in (CALL_STYLE_PARAMS, CALL_STYLE_FLAT)


def test_unlisted_tools_are_rejected():
    for name in (
        "host_create",
        "problem_delete",
        "event_acknowledge",
        "raw_api_call",
        "user_login",
        "HOST_GET",  # case-sensitive: must not match
        "host_get ",  # no trimming: must not match
        "",
        None,
        123,
    ):
        assert is_allowed(name) is False
        assert role_of(name) is None
        assert call_style(name) is None


def test_no_write_like_tools_in_catalog():
    for name in all_tools():
        lowered = name.lower()
        assert "create" not in lowered
        assert "update" not in lowered
        assert "delete" not in lowered
        assert "acknowledge" not in lowered
        assert lowered != "raw_api_call"


def test_all_tools_use_flat_args_on_hub_1_36_1():
    # Verified live 2026-10-07: the hub ignores the 'params' wrapper.
    for name in all_tools():
        assert call_style(name) == CALL_STYLE_FLAT


def test_lab_verified_tools_are_present():
    # Called against the live hub during the Fase 2 spike.
    for name in ("problem_active_get", "host_status_get", "host_get"):
        assert is_allowed(name) is True


def test_validate_catalog_rejects_bad_data():
    with pytest.raises(ValueError):
        validate_catalog({"roles": {}})
    with pytest.raises(ValueError):
        validate_catalog({"roles": {"operator": [{"name": "host_create"}]}})
    tiny = {"roles": {"operator": [{"name": "host_get", "args": "params"}]}}
    with pytest.raises(ValueError):
        validate_catalog(tiny)


def test_l2_answer_references_curated_catalog():
    from agent.router import L2_FALLBACK, route

    level, text = route("correlaciona la causa raiz con runbooks", object())
    assert level == "L2"
    assert text.startswith(L2_FALLBACK)
    assert "mcp/curated-tools.json" in text
