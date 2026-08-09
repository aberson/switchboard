"""Endpoint health + warmth probes.

Callers use these to decide whether to even attempt a local offload:

* ``health(cfg)`` — GET ``{base_url}/models``; returns reachability + the served model ids.
* ``is_warm(cfg)`` — is the configured model served right now (cheap reachability proxy)?
* ``warm_up(cfg)`` — optional: fire a tiny judge request to trigger a cold-load so the
  next real call is warm. Returns whether it landed a verdict (model is now hot).

All probes are sync, stdlib-only, and never raise on a down endpoint — they return a
structured ``Health`` instead, mirroring ``local_judge``'s defer-not-throw discipline.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Literal, TypedDict

from switchboard.client import local_judge
from switchboard.config import SwitchboardConfig

# A models-list probe is cheap; keep its timeout short and independent of the judge timeouts.
MODELS_PROBE_TIMEOUT_S = 10.0


class Health(TypedDict):
    """Result of a ``/models`` reachability probe."""

    reachable: bool
    models: list[str]
    model_served: bool
    error: str | None


EndpointStatus = Literal["offline", "online-model-missing", "online-model-served"]
ENDPOINT_STATUSES: tuple[EndpointStatus, ...] = (
    "offline",
    "online-model-missing",
    "online-model-served",
)


def endpoint_status(result: Health) -> EndpointStatus:
    """Classify probe facts without equating reachability with a served configured model."""
    if not result["reachable"]:
        return "offline"
    return "online-model-served" if result["model_served"] else "online-model-missing"


def health(
    config: SwitchboardConfig | None = None,
    *,
    timeout: float = MODELS_PROBE_TIMEOUT_S,
) -> Health:
    """GET ``{base_url}/models``. Never raises; reports reachability + served models."""
    cfg = config if config is not None else SwitchboardConfig()
    req = urllib.request.Request(f"{cfg.base_url}/models", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload_raw = json.loads(resp.read().decode("utf-8"))
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        return {"reachable": False, "models": [], "model_served": False, "error": repr(exc)}
    except (json.JSONDecodeError, ValueError) as exc:
        return {
            "reachable": True,
            "models": [],
            "model_served": False,
            "error": f"non-JSON /models body: {exc!r}",
        }

    models = _model_ids(payload_raw)
    return {
        "reachable": True,
        "models": models,
        "model_served": cfg.model in models,
        "error": None,
    }


def is_warm(
    config: SwitchboardConfig | None = None,
    *,
    timeout: float = MODELS_PROBE_TIMEOUT_S,
) -> bool:
    """True if the endpoint is reachable AND the configured model is in the served list.

    NOTE: llama-swap lists a model as available even when it is cold-unloaded, so a True
    here means "the endpoint will accept this model", not "the next call is sub-second".
    Use ``warm_up`` to force an actual load.
    """
    return health(config, timeout=timeout)["model_served"]


def warm_up(config: SwitchboardConfig | None = None) -> bool:
    """Fire a tiny judge request with the COLD timeout to trigger a model load.

    Returns True if the warm-up landed a real verdict (the model is now hot); False if it
    deferred (endpoint down, or it cold-loaded but still deferred — caller should retry).
    """
    cfg = config if config is not None else SwitchboardConfig()
    result = local_judge(
        "Code-style diff under review:\n- x=1\n+ x = 1\n\nTrivial whitespace fix. "
        'Respond with ONLY JSON: {"verdict":"pass"|"flag","reason":"<short>"}',
        config=cfg,
        cold=True,
    )
    return "defer" not in result


def _model_ids(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for entry in data:
        if isinstance(entry, dict):
            mid = entry.get("id")
            if isinstance(mid, str):
                ids.append(mid)
    return ids
