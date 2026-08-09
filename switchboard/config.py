"""Switchboard configuration.

Holds the offload-core knobs:

* ``less_token_mode`` — the global on/off toggle. When OFF, ``local_judge`` short-circuits
  to the defer sentinel WITHOUT calling the endpoint (callers fall back to Claude).
* ``enabled_call_sites`` — a ``task_class -> bool | model`` map gating which call sites are
  allowed to offload locally, and (optionally) pinning a model per call site.
* endpoint ``base_url`` + ``model`` + ``cold_timeout_s`` / ``warm_timeout_s`` / ``max_tokens``
  with the spike-pinned defaults.

All values are light-validated at construction (``__post_init__``) so a malformed config
fails loudly at the boundary rather than silently producing a bad request later.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, cast

# --- Spike-pinned defaults (docs/investigations/switchboard-spike.md, D1 contract) -------
DEFAULT_BASE_URL = "http://localhost:8080/v1"
DEFAULT_MODEL = "coder-30b"

# coder-30b cold-loads on first hit (~200 s observed; general-35b, if ever served, 130-264 s).
# Warm calls are ~16-22 s, so the warm ceiling stays well above that with headroom.
DEFAULT_COLD_TIMEOUT_S = 540.0
DEFAULT_WARM_TIMEOUT_S = 60.0

# max_tokens is sized for generous headroom. coder-30b (Qwen3-Coder-30B-A3B-Instruct) is a
# NON-reasoning model, so a verdict needs few tokens; the 800 default / 600 floor are safe
# headroom retained from the general-35b era (a reasoning model that spent ~400-620 tokens on
# reasoning_content before the answer, truncating with content="" and finish_reason="length"
# under a small budget). Kept generous because a reasoning model may still be transiently
# served and over-provisioning a cheap local call is harmless; we hard-reject < 600.
DEFAULT_MAX_TOKENS = 800
MIN_MAX_TOKENS = 600

# base_url must look like an http(s) URL with no obvious injection / path-traversal chars.
_BASE_URL_RE = re.compile(r"^https?://[A-Za-z0-9._:\-]+(?:/[A-Za-z0-9._\-/]*)?$")

# model / task_class names: identifier-ish tokens only (no whitespace, no path separators,
# no shell/URL metacharacters). Keeps a hostile config value from leaking into the request
# body or being mistaken for a path.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._\-]+$")

# The reasoning-effort tiers a Claude-side sub-agent dispatch (Workflow/Agent reasoning_effort)
# can be set to. This is the ONLY value set the ``effort`` map accepts. See the honest-scope
# note on ``SwitchboardConfig.effort`` below: switchboard stores + validates + round-trips this
# dimension but does NOT act on it — the local_judge urllib client has no effort knob; effort
# is consumed Claude-side when dispatching the slice's sub-agents, not by the local endpoint.
ALLOWED_EFFORT_TIERS: frozenset[str] = frozenset({"low", "medium", "high", "xhigh", "max"})


class ConfigError(ValueError):
    """Raised when a Switchboard config value fails validation."""


def _validate_name(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{label} must be a non-empty string, got {value!r}")
    if not _SAFE_NAME_RE.match(value):
        raise ConfigError(
            f"{label} {value!r} contains unsafe characters "
            f"(allowed: letters, digits, '.', '_', '-')"
        )
    return value


@dataclass(frozen=True, slots=True)
class SwitchboardConfig:
    """Immutable, validated Switchboard configuration.

    ``enabled_call_sites`` maps a ``task_class`` (e.g. ``"style-lens"``) to either:
      * ``True``  — offload allowed, use the default ``model``;
      * ``False`` — offload disabled for this call site (defer to Claude);
      * a model name ``str`` — offload allowed, pin this model for the call site.

    NOTE: per D2 the production deployment uses ONE model (coder-30b) for all slices.
    The per-site model override exists for config expressiveness only; no model-swap
    routing is built into the client.

    ``effort`` maps a ``task_class`` to a Claude-side reasoning-effort tier (one of
    ``ALLOWED_EFFORT_TIERS``). HONEST SCOPE (Phase B / Step B3): this dimension is consumed by
    **Claude-side sub-agent dispatch** (a Workflow/Agent ``reasoning_effort`` override when the
    slice's judges run on Claude), NOT by ``local_judge`` — the local urllib client talks to one
    local model and has no effort knob. switchboard *stores + validates + round-trips* ``effort``
    so a config can carry the recommendation, but NOTHING in this package acts on it; there is no
    live consumer wired this phase, and that is deliberate (see the bake-off effort-vs-model arm +
    docs/effort-vs-model-recommendation.md). Do NOT add a code path that pretends to honor it.
    """

    less_token_mode: bool = True
    enabled_call_sites: dict[str, bool | str] = field(default_factory=dict)
    effort: dict[str, str] = field(default_factory=dict)
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    cold_timeout_s: float = DEFAULT_COLD_TIMEOUT_S
    warm_timeout_s: float = DEFAULT_WARM_TIMEOUT_S
    max_tokens: int = DEFAULT_MAX_TOKENS

    def __post_init__(self) -> None:
        if not isinstance(self.less_token_mode, bool):
            raise ConfigError(f"less_token_mode must be a bool, got {self.less_token_mode!r}")

        if (
            not isinstance(self.base_url, str)
            or not _BASE_URL_RE.match(self.base_url)
            or ".." in self.base_url
        ):
            raise ConfigError(f"base_url {self.base_url!r} is not a safe http(s) URL")

        _validate_name(self.model, "model")

        for tc, val in self.enabled_call_sites.items():
            _validate_name(tc, "task_class")
            if isinstance(val, bool):
                continue
            if isinstance(val, str):
                _validate_name(val, f"enabled_call_sites[{tc!r}] model")
            else:
                raise ConfigError(
                    f"enabled_call_sites[{tc!r}] must be bool or model name str, got {val!r}"
                )

        for tc, tier in self.effort.items():
            _validate_name(tc, "task_class")
            if not isinstance(tier, str) or tier not in ALLOWED_EFFORT_TIERS:
                raise ConfigError(
                    f"effort[{tc!r}] must be one of {sorted(ALLOWED_EFFORT_TIERS)}, got {tier!r}"
                )

        for label, tval in (
            ("cold_timeout_s", self.cold_timeout_s),
            ("warm_timeout_s", self.warm_timeout_s),
        ):
            if not isinstance(tval, (int, float)) or isinstance(tval, bool) or tval <= 0:
                raise ConfigError(f"{label} must be a positive number, got {tval!r}")

        if (
            not isinstance(self.max_tokens, int)
            or isinstance(self.max_tokens, bool)
            or self.max_tokens < MIN_MAX_TOKENS
        ):
            raise ConfigError(
                f"max_tokens must be an int >= {MIN_MAX_TOKENS} "
                f"(verdict + reasoning-budget headroom floor), got {self.max_tokens!r}"
            )

    @classmethod
    def from_mapping(cls, data: Mapping[str, object]) -> SwitchboardConfig:
        """Construct from a mapping, rejecting any unknown top-level key with ConfigError.

        ``SwitchboardConfig(**data)`` would raise a raw ``TypeError`` on an unexpected kwarg;
        this surfaces a clean ``ConfigError`` naming the offending key(s) instead. Value
        validation is still done by ``__post_init__`` once the keys are known-good. The
        allow-list is the single source of truth ``ALLOWED_TOP_LEVEL_FIELDS`` (derived from
        the dataclass fields) so the producer (/offload-scan), this consumer, and the
        round-trip test can never drift — see code-quality.md one-source-of-truth discipline.
        """
        unknown = set(data) - ALLOWED_TOP_LEVEL_FIELDS
        if unknown:
            raise ConfigError(
                f"unknown config key(s): {sorted(unknown)}; "
                f"allowed: {sorted(ALLOWED_TOP_LEVEL_FIELDS)}"
            )
        # Values are object-typed at the boundary; __post_init__ does the real validation.
        return cls(**cast("Mapping[str, Any]", data))

    def is_call_site_enabled(self, task_class: str) -> bool:
        """True if this call site may offload locally (given less_token_mode is ON).

        An unknown task_class (not in the map) is disabled-by-default — callers must
        opt a site in explicitly.
        """
        val = self.enabled_call_sites.get(task_class)
        if val is None:
            return False
        if isinstance(val, bool):
            return val
        # A model-name string opts the site in.
        return True

    def model_for(self, task_class: str) -> str:
        """The model to use for a call site: the per-site override if a str, else default."""
        val = self.enabled_call_sites.get(task_class)
        if isinstance(val, str):
            return val
        return self.model

    def offload_allowed(self, task_class: str | None = None) -> bool:
        """Top-level gate: less_token_mode ON AND (no call site given OR site enabled)."""
        if not self.less_token_mode:
            return False
        if task_class is None:
            return True
        return self.is_call_site_enabled(task_class)

    def effort_for(self, task_class: str) -> str | None:
        """The configured Claude-side effort tier for a call site, or None if unset.

        Read-only lookup: switchboard does not act on the returned tier (no live consumer this
        phase — see the ``effort`` field docstring). A caller that *does* dispatch the slice's
        judges on Claude can read this to set the sub-agent ``reasoning_effort``; ``local_judge``
        ignores it entirely.
        """
        return self.effort.get(task_class)


@dataclass(frozen=True, slots=True)
class SiteInspection:
    """One configured site's read-only effective routing facts for ``inspect``.

    A site can be present only in the ``effort`` map, explicitly disabled, enabled
    with the default model, or enabled with a model pin.  All of those states remain
    distinct in the serialized report; in particular, a false value is not treated as
    an absent setting and an absent effort hint stays ``None`` rather than a made-up
    tier.
    """

    site: str
    configured_value: bool | str | None
    configured_model: str | None
    default_model: str
    effective_model: str
    site_enabled: bool
    offload_allowed: bool
    effort_hint: str | None

    def to_json(self) -> dict[str, object]:
        return {
            "site": self.site,
            "configured_value": self.configured_value,
            "configured_model": self.configured_model,
            "default_model": self.default_model,
            "effective_model": self.effective_model,
            "site_enabled": self.site_enabled,
            "offload_allowed": self.offload_allowed,
            "effort_hint": self.effort_hint,
        }


def inspect_sites(config: SwitchboardConfig) -> tuple[SiteInspection, ...]:
    """Return each configured site's effective model and gate facts in stable order."""
    names = sorted(set(config.enabled_call_sites) | set(config.effort))
    return tuple(
        SiteInspection(
            site=site,
            configured_value=config.enabled_call_sites.get(site),
            configured_model=(
                value if isinstance(value := config.enabled_call_sites.get(site), str) else None
            ),
            default_model=config.model,
            effective_model=config.model_for(site),
            site_enabled=config.is_call_site_enabled(site),
            offload_allowed=config.offload_allowed(site),
            effort_hint=config.effort_for(site),
        )
        for site in names
    )


# The single source of truth for "which top-level keys a config file may contain": the
# dataclass field set. from_mapping() and the offload-scan round-trip test both import this,
# so adding a config field can never desync the producer, the consumer, and the test.
ALLOWED_TOP_LEVEL_FIELDS: frozenset[str] = frozenset(f.name for f in fields(SwitchboardConfig))

# Env var an operator sets to point at a config file (highest precedence after an explicit arg).
ENV_VAR = "SWITCHBOARD_CONFIG"

# Public contract facts used by the observatory fixture and its drift test.
CONFIG_DIRECTORY_NAME = ".switchboard"
CONFIG_FILENAME = "config.json"
CONFIG_SOURCE_PRECEDENCE: tuple[str, ...] = ("arg", "env", "home", "defaults")


@dataclass(frozen=True, slots=True)
class _ConfigSource:
    """One resolved config source, factored so inspect and load share precedence."""

    candidate: str | None
    label_prefix: str
    require_exists: bool

    @property
    def label(self) -> str:
        return "defaults" if self.candidate is None else f"{self.label_prefix}:{self.candidate}"


def _default_config_path() -> Path:
    """The home-directory default config location.

    Factored into its own function so tests can monkeypatch it and never read a real
    ``~/.switchboard/config.json`` that happens to exist on the dev machine.
    """
    return Path.home() / CONFIG_DIRECTORY_NAME / CONFIG_FILENAME


def _resolve_config_source(path: str | None = None) -> _ConfigSource:
    """Resolve config precedence without opening the selected file."""
    if path is not None:
        return _ConfigSource(candidate=path, label_prefix="arg", require_exists=True)

    env_path = os.environ.get(ENV_VAR)
    if env_path:
        return _ConfigSource(candidate=env_path, label_prefix="env", require_exists=True)

    home = _default_config_path()
    if home.is_file():
        return _ConfigSource(candidate=str(home), label_prefix="home", require_exists=False)
    return _ConfigSource(candidate=None, label_prefix="", require_exists=False)


def config_source_label(path: str | None = None) -> str:
    """Return the source selected by normal precedence, even if its content is invalid."""
    return _resolve_config_source(path).label


def load_config(path: str | None = None) -> tuple[SwitchboardConfig, str]:
    """Resolve, read, and validate a Switchboard config; return ``(config, source_label)``.

    Resolution order (first hit wins):

      1. explicit ``path`` arg                 -> source ``"arg:<path>"``
      2. ``$SWITCHBOARD_CONFIG`` env var       -> source ``"env:<path>"``
      3. ``~/.switchboard/config.json``        -> source ``"home:<path>"``
      4. none of the above                     -> ``(SwitchboardConfig(), "defaults")``

    Tiers 1 and 2 are *explicit*: the operator named a file, so a missing/unreadable/invalid
    one raises ``ConfigError`` — silently ignoring it would be the silent-off failure mode
    operators hate. Tier 3 is *implicit*: it counts as a source only when the file exists; a
    missing home file falls through to inert defaults (byte-identical to today). Once a file is
    selected, any read / JSON / validation failure raises ``ConfigError`` regardless of tier.

    The ``judge`` hot path wraps this defer-safely (a ConfigError there degrades to a Claude
    fallback, never a crash); the ``config`` subcommand lets it raise so the operator sees it.
    """
    source = _resolve_config_source(path)
    if source.candidate is None:
        return SwitchboardConfig(), "defaults"

    candidate = source.candidate
    p = Path(candidate)
    if source.require_exists and not p.is_file():
        raise ConfigError(f"config file not found: {candidate!r}")

    try:
        with p.open(encoding="utf-8") as fh:
            raw = json.load(fh)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        # UnicodeDecodeError (invalid UTF-8 bytes) subclasses ValueError, NOT OSError — it must
        # be caught explicitly or it escapes as a non-ConfigError and breaks defer-safety.
        raise ConfigError(f"could not read config {candidate!r}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"config {candidate!r} must be a JSON object, got {type(raw).__name__}")

    cfg = SwitchboardConfig.from_mapping(cast("Mapping[str, object]", raw))
    return cfg, source.label
