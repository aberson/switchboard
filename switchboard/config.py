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

import re
from dataclasses import dataclass, field

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
