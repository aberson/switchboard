"""CLI judge entrypoint: --site/--slice equivalence, gating short-circuit, exit-0 contract.

The CLI is the seam a wired SKILL.md drives. The load-bearing guarantees:
  * gated INERT by default — an un-enabled site (or offload off) DEFERS with NO network;
  * exit code is ALWAYS 0 for a well-formed judge invocation (a defer is not an error);
  * stdout is exactly one JSON object the caller parses to decide verdict-vs-defer.

Like test_client, network is stubbed (patch_client) — these tests never call the endpoint.
``run_judge`` accepts an explicit ``config`` so we can drive the gate without env state.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest

from switchboard.cli import main, run_judge
from switchboard.config import SwitchboardConfig
from switchboard.metrics import Metrics
from tests.conftest import PASS_CONTENT, chat_envelope, make_json_urlopen

UrlopenStub = Callable[..., object]
ApplyStub = Callable[[UrlopenStub], None]


# --- run_judge: gating short-circuit is inert (no network) -------------------------------


def test_run_judge_defers_when_offload_off() -> None:
    # No patch_client: a network touch would hit an absent endpoint and fail the test.
    cfg = SwitchboardConfig(less_token_mode=False)
    m = Metrics()
    result = run_judge(slice_name="review-deep-style", prompt="judge this", config=cfg, metrics=m)

    assert result["defer"] is True  # type: ignore[typeddict-item]
    assert result["reason_class"] == "disabled"  # type: ignore[typeddict-item]
    assert m.defers["disabled"] == 1


def test_run_judge_defers_when_site_disabled() -> None:
    # less_token_mode ON, but this site is explicitly disabled (the build-step-style case).
    cfg = SwitchboardConfig(
        less_token_mode=True, enabled_call_sites={"build-step-style": False}
    )
    result = run_judge(slice_name="build-step-style", prompt="judge this", config=cfg)
    assert result["defer"] is True  # type: ignore[typeddict-item]
    assert result["reason_class"] == "disabled"  # type: ignore[typeddict-item]


def test_run_judge_routes_local_when_site_enabled(patch_client: ApplyStub) -> None:
    patch_client(make_json_urlopen(chat_envelope(PASS_CONTENT)))
    cfg = SwitchboardConfig(enabled_call_sites={"review-deep-style": True})
    m = Metrics()
    result = run_judge(slice_name="review-deep-style", prompt="judge this", config=cfg, metrics=m)
    assert result["verdict"] == "pass"  # type: ignore[typeddict-item]
    assert m.verdicts["pass"] == 1


# --- main(): exit-0 contract + one-JSON-object stdout ------------------------------------


def test_main_disabled_site_exits_0_prints_defer(capsys: pytest.CaptureFixture[str]) -> None:
    # Default config: no call sites enabled, so any --site defers without network. Exit 0.
    rc = main(["judge", "--site", "review-deep-style", "--prompt", "judge this"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["defer"] is True
    assert out["reason_class"] == "disabled"


def test_main_slice_alias_equivalent_to_site(capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["judge", "--slice", "review-deep-style", "--prompt", "x"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["defer"] is True


def test_main_requires_exactly_one_of_site_or_slice() -> None:
    # Neither given -> argparse usage error (a caller bug, distinct from a defer).
    with pytest.raises(SystemExit) as exc:
        main(["judge", "--prompt", "x"])
    assert exc.value.code != 0


def test_main_site_and_slice_mutually_exclusive() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["judge", "--site", "a", "--slice", "b", "--prompt", "x"])
    assert exc.value.code != 0


def test_main_stdout_is_single_json_object(capsys: pytest.CaptureFixture[str]) -> None:
    main(["judge", "--site", "review-deep-style", "--prompt", "x"])
    out = capsys.readouterr().out
    # Exactly one JSON object then a trailing newline — the caller does json.loads(out).
    assert out.endswith("\n")
    json.loads(out)  # raises if not exactly one object


def test_read_prompt_precedence_prompt_over_file(tmp_path: pytest.TempPathFactory) -> None:
    from switchboard.cli import _read_prompt

    p = tmp_path / "prompt.txt"  # type: ignore[operator]
    p.write_text("from-file", encoding="utf-8")
    # Explicit --prompt wins over --prompt-file.
    assert _read_prompt(str(p), "from-string") == "from-string"
    assert _read_prompt(str(p), None) == "from-file"
