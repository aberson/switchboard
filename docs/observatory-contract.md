# Switchboard observatory contract

`observatory-contract.json` is Switchboard's versioned, producer-owned configuration, registry and
inspection contract (fixture `schema_version` 2). It is a static fixture, not a live probe and not
authority to enable or launch anything. Consumers may display it beside a current
`python -m switchboard inspect --json` result.

The `config` section names every accepted config field, the exact filename and selection
precedence, default values and validation boundaries. `effort` remains a Claude-side hint only:
Switchboard validates and reports it but the local judge client does not consume it. The retired
`roles` and `claims` config keys are listed under `retired_fields`; a config carrying either fails
as an unknown key.

The `registry` section describes the committed `registry/models.json` (registry `schema_version`
1): its resolution order (`--registry`, `SWITCHBOARD_REGISTRY`, the repo default), the `absent`,
`invalid` and `ok` states, the exact role vocabulary, row and host fields, the per-host effort
levels, and the model rules (exact IDs or `inherit`; no bare aliases; no model containing
`fable` in any case, so no `claude-fable-*`).

The `inspect` section (inspect `schema_version` 3) names every report and roles-view field, the
role row and host-pin fields, and every inspect, endpoint and registry state. Role rows are
requested values only: switchboard does not dispatch by role.

## Update rule

When changing any config field, default, source path, validation boundary, registry field or rule,
or inspect field or state, update this JSON fixture in the same change. `tests/test_config.py`,
`tests/test_cli.py` and `tests/test_registry.py` compare the fixture with runtime constants and
real report shapes, so an unpaired change fails CI.

## Consumer boundary

Switchboard owns config truth and bounded health facts. A consumer must not infer endpoint health,
successful model service, outcome evidence, certification, or call-site wiring from this fixture.
dev-observatory owns workspace caller/pin proof separately.
