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
DEFAULT_MODEL = "general-35b"

# general-35b cold-loads on first hit (130-264 s observed). Warm calls are 16-22 s but
# reasoning-token generation can push past 20 s, so the warm ceiling stays well above that.
DEFAULT_COLD_TIMEOUT_S = 540.0
DEFAULT_WARM_TIMEOUT_S = 60.0

# general-35b (Qwen3.6-35B-A3B) is a reasoning model: it spends ~400-620 tokens on
# reasoning_content before the answer lands in content. A small budget truncates with
# content="" and finish_reason="length". 800 is the pinned floor; we hard-reject < 600.
DEFAULT_MAX_TOKENS = 800
MIN_MAX_TOKENS = 600

# base_url must look like an http(s) URL with no obvious injection / path-traversal chars.
_BASE_URL_RE = re.compile(r"^https?://[A-Za-z0-9._:\-]+(?:/[A-Za-z0-9._\-/]*)?$")

# model / task_class names: identifier-ish tokens only (no whitespace, no path separators,
# no shell/URL metacharacters). Keeps a hostile config value from leaking into the request
# body or being mistaken for a path.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._\-]+$")


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

    NOTE: per D2 the production deployment uses ONE model (general-35b) for all slices.
    The per-site model override exists for config expressiveness only; no model-swap
    routing is built into the client.
    """

    less_token_mode: bool = True
    enabled_call_sites: dict[str, bool | str] = field(default_factory=dict)
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
                f"(general-35b is a reasoning model), got {self.max_tokens!r}"
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


# The single source of truth for "which top-level keys a config file may contain": the
# dataclass field set. from_mapping() and the offload-scan round-trip test both import this,
# so adding a config field can never desync the producer, the consumer, and the test.
ALLOWED_TOP_LEVEL_FIELDS: frozenset[str] = frozenset(f.name for f in fields(SwitchboardConfig))

# Env var an operator sets to point at a config file (highest precedence after an explicit arg).
ENV_VAR = "SWITCHBOARD_CONFIG"


def _default_config_path() -> Path:
    """The home-directory default config location.

    Factored into its own function so tests can monkeypatch it and never read a real
    ``~/.switchboard/config.json`` that happens to exist on the dev machine.
    """
    return Path.home() / ".switchboard" / "config.json"


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
    candidate: str | None = None
    label_prefix = ""
    require_exists = False

    if path is not None:
        candidate, label_prefix, require_exists = path, "arg", True
    else:
        env_path = os.environ.get(ENV_VAR)
        if env_path:
            candidate, label_prefix, require_exists = env_path, "env", True
        else:
            home = _default_config_path()
            if home.is_file():
                # Already confirmed to exist; treat any later read failure as an error.
                candidate, label_prefix = str(home), "home"

    if candidate is None:
        return SwitchboardConfig(), "defaults"

    p = Path(candidate)
    if require_exists and not p.is_file():
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
    return cfg, f"{label_prefix}:{candidate}"
