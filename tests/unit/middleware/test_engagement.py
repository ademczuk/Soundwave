"""Tests for EngagementContextMiddleware — engagement and benchmark inject paths."""

from __future__ import annotations

from typing import Any

import pytest
from langchain.agents import AgentState
from langchain.agents.factory import _resolve_schemas
from langchain_core.messages import SystemMessage
from langgraph.graph import END, START, StateGraph

from decepticon.middleware.engagement import (
    EngagementContextMiddleware,
    EngagementContextState,
    _benchmark_mode_active,
)
from decepticon.middleware.opplan import OPPLANState


class _FakeRequest:
    """Minimal duck-typed stand-in for the AgentMiddleware request object."""

    def __init__(
        self,
        state: dict[str, Any] | None = None,
        system_message: SystemMessage | None = None,
    ) -> None:
        self.state = state or {}
        self.system_message = system_message

    def override(self, system_message: SystemMessage) -> "_FakeRequest":
        return _FakeRequest(state=self.state, system_message=system_message)


def _flatten(message: SystemMessage | None) -> str:
    """Return the concatenated text of a SystemMessage regardless of content shape."""
    if message is None:
        return ""
    content = message.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            text = block.get("text", "")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


@pytest.fixture
def middleware() -> EngagementContextMiddleware:
    """Subagent-role middleware (default)."""
    return EngagementContextMiddleware()


@pytest.fixture
def orchestrator_middleware() -> EngagementContextMiddleware:
    """Orchestrator-role middleware (gets RULES_OVERRIDE + cross-domain skill paths)."""
    return EngagementContextMiddleware(role="orchestrator")


@pytest.fixture(autouse=True)
def _clear_benchmark_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default each test to BENCHMARK_MODE unset; tests opt-in via monkeypatch.setenv."""
    monkeypatch.delenv("BENCHMARK_MODE", raising=False)


# ── env-var helper ─────────────────────────────────────────────────────


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", "anything"])
def test_benchmark_mode_active_truthy(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("BENCHMARK_MODE", value)
    assert _benchmark_mode_active() is True


@pytest.mark.parametrize("value", ["", "0", "false", "FALSE", "no", "off", "  "])
def test_benchmark_mode_active_falsy(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("BENCHMARK_MODE", value)
    assert _benchmark_mode_active() is False


def test_benchmark_mode_active_unset() -> None:
    # autouse fixture deletes the env; must be False.
    assert _benchmark_mode_active() is False


@pytest.mark.parametrize(
    "schema",
    [
        OPPLANState,
        EngagementContextState,
        _resolve_schemas({AgentState, OPPLANState, EngagementContextState})[0],
    ],
)
def test_engagement_name_reducer_handles_concurrent_updates(schema) -> None:
    def set_name(_state):
        return {"engagement_name": "demo-engagement"}

    def keep_name(_state):
        return {"engagement_name": None}

    graph = StateGraph(schema)
    graph.add_node("set_name", set_name)
    graph.add_node("keep_name", keep_name)
    graph.add_edge(START, "set_name")
    graph.add_edge(START, "keep_name")
    graph.add_edge("set_name", END)
    graph.add_edge("keep_name", END)

    result = graph.compile().invoke({"messages": []})

    assert result["engagement_name"] == "demo-engagement"


# ── inject paths ───────────────────────────────────────────────────────


def test_no_injection_returns_request_unchanged(
    middleware: EngagementContextMiddleware,
) -> None:
    req = _FakeRequest(state={})
    result = middleware._inject(req)
    assert result is req
    assert result.system_message is None


def test_engagement_only_injection(middleware: EngagementContextMiddleware) -> None:
    req = _FakeRequest(
        state={"engagement_name": "blue-falcon", "workspace_path": "/workspace"},
    )
    result = middleware._inject(req)

    assert result is not req  # override produced a fresh request
    text = _flatten(result.system_message)
    assert "Workspace slug: blue-falcon" in text
    assert "Workspace root: /workspace" in text
    assert "BENCHMARK MODE" not in text  # benchmark section absent


def test_benchmark_mode_env_off_does_not_inject_challenge_context(
    middleware: EngagementContextMiddleware,
) -> None:
    """Even with full challenge state, no inject when BENCHMARK_MODE is unset."""
    req = _FakeRequest(
        state={
            "target_url": "http://host.docker.internal:8080",
            "vulnerability_tags": ["sqli"],
            "flag_format": "FLAG{<64-char-hex>}",
            "mission_brief": "Test challenge",
        },
    )
    result = middleware._inject(req)

    # No engagement_name and benchmark off → return original request.
    assert result is req


def test_benchmark_mode_env_on_injects_rules_override_for_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    orchestrator_middleware: EngagementContextMiddleware,
) -> None:
    """BENCHMARK_MODE=1 + orchestrator role → rule-suspension addendum is injected."""
    monkeypatch.setenv("BENCHMARK_MODE", "1")
    req = _FakeRequest(state={})
    result = orchestrator_middleware._inject(req)

    text = _flatten(result.system_message)
    assert "[BENCHMARK MODE — engaged]" in text
    assert "Rule 8 (Startup Required)" in text
    assert "Rule 9 (Final Report)" in text
    assert "RECON objective" in text


def test_benchmark_mode_subagent_omits_rules_override_and_exploit_paths(
    monkeypatch: pytest.MonkeyPatch,
    middleware: EngagementContextMiddleware,
) -> None:
    """Subagent role: NO rule-suspension block, NO cross-domain skill path hints.

    Per-challenge context (target URL, tags, flag format, brief) IS still
    injected so the sub-agent knows what it's attacking.
    """
    monkeypatch.setenv("BENCHMARK_MODE", "1")
    req = _FakeRequest(
        state={
            "target_url": "http://x",
            "vulnerability_tags": ["idor"],
            "flag_format": "FLAG{...}",
            "mission_brief": "test",
        }
    )
    result = middleware._inject(req)

    text = _flatten(result.system_message)
    # Orchestrator-only blocks must be absent.
    assert "[BENCHMARK MODE — engaged]" not in text
    assert "Rule 8 (Startup Required)" not in text
    assert "RECON objective" not in text
    assert "/skills/exploit/web/" not in text
    assert "/skills/benchmark/SKILL.md" not in text
    # Per-challenge context must still be present.
    assert "## CTF Benchmark Challenge" in text
    assert "**Target URL:** http://x" in text
    assert "**Vulnerability tags:** idor" in text
    assert "**Flag format:** FLAG{...}" in text
    assert "**Mission brief:** test" in text


def test_benchmark_mode_full_context(
    monkeypatch: pytest.MonkeyPatch,
    orchestrator_middleware: EngagementContextMiddleware,
) -> None:
    monkeypatch.setenv("BENCHMARK_MODE", "1")
    req = _FakeRequest(
        state={
            "engagement_name": "benchmark-XBEN-001-24",
            "workspace_path": "/workspace/benchmark-XBEN-001-24",
            "target_url": "http://host.docker.internal:33001",
            "target_extra_ports": {},
            "vulnerability_tags": ["sqli", "auth-bypass"],
            "flag_format": "FLAG{<64-char-hex>}",
            "mission_brief": "Login Form SQLi — bypass authentication",
        },
    )
    result = orchestrator_middleware._inject(req)

    text = _flatten(result.system_message)
    # engagement section
    assert "Workspace slug: benchmark-XBEN-001-24" in text
    # benchmark section (orchestrator gets full block)
    assert "[BENCHMARK MODE — engaged]" in text
    assert "## CTF Benchmark Challenge" in text
    assert "**Target URL:** http://host.docker.internal:33001" in text
    assert "Attack ONLY this URL" in text
    assert "**Vulnerability tags:** sqli, auth-bypass" in text
    assert "**Flag format:** FLAG{<64-char-hex>}" in text
    assert "**Mission brief:** Login Form SQLi — bypass authentication" in text
    # exploit-skill path hint included for orchestrator
    assert "/skills/exploit/web/" in text
    # engagement section comes before benchmark section
    assert text.index("Workspace slug:") < text.index("[BENCHMARK MODE")


def test_benchmark_extra_ports(
    monkeypatch: pytest.MonkeyPatch,
    middleware: EngagementContextMiddleware,
) -> None:
    monkeypatch.setenv("BENCHMARK_MODE", "1")
    req = _FakeRequest(
        state={
            "target_url": "http://host.docker.internal:33001",
            "target_extra_ports": {22: 2222, 3306: 33060},
            "vulnerability_tags": ["sqli"],
        },
    )
    result = middleware._inject(req)

    text = _flatten(result.system_message)
    assert "**Additional services:**" in text
    assert "**SSH:** host.docker.internal:2222 (internal port 22)" in text
    assert "**Port 3306:** host.docker.internal:33060" in text


def test_benchmark_extra_ports_empty_does_not_emit_section(
    monkeypatch: pytest.MonkeyPatch,
    middleware: EngagementContextMiddleware,
) -> None:
    monkeypatch.setenv("BENCHMARK_MODE", "1")
    req = _FakeRequest(
        state={
            "target_url": "http://host.docker.internal:33001",
            "target_extra_ports": {},
        },
    )
    result = middleware._inject(req)
    text = _flatten(result.system_message)
    assert "Additional services" not in text


def test_appended_to_existing_system_message(
    monkeypatch: pytest.MonkeyPatch,
    orchestrator_middleware: EngagementContextMiddleware,
) -> None:
    """When the request already has a system message, content_blocks are extended."""
    monkeypatch.setenv("BENCHMARK_MODE", "1")
    req = _FakeRequest(
        state={"engagement_name": "demo", "workspace_path": "/workspace"},
        system_message=SystemMessage(content="ORIGINAL_PROMPT_BODY"),
    )
    result = orchestrator_middleware._inject(req)
    text = _flatten(result.system_message)
    # original content is preserved; addendum is appended.
    assert "ORIGINAL_PROMPT_BODY" in text
    assert "Workspace slug: demo" in text
    assert "[BENCHMARK MODE — engaged]" in text
    assert text.index("ORIGINAL_PROMPT_BODY") < text.index("Workspace slug")


def test_benchmark_with_missing_optional_fields(
    monkeypatch: pytest.MonkeyPatch,
    middleware: EngagementContextMiddleware,
) -> None:
    """Empty optional fields are silently skipped — only non-empty pieces appear."""
    monkeypatch.setenv("BENCHMARK_MODE", "1")
    req = _FakeRequest(state={"target_url": "http://x"})
    result = middleware._inject(req)
    text = _flatten(result.system_message)

    assert "**Target URL:** http://x" in text
    # No tags / flag_format / brief sections.
    assert "**Vulnerability tags:**" not in text
    assert "**Flag format:**" not in text
    assert "**Mission brief:**" not in text
