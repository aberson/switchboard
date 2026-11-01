# Switchboard observatory contract

`observatory-contract.json` is Switchboard's versioned, producer-owned configuration and
inspection contract. It is a static fixture, not a live probe and not authority to enable or launch
anything. Consumers may display it beside a current `python -m switchboard inspect --json` result.

The fixture names every accepted config field, the exact filename and selection precedence, default
values, validation boundaries, and every `inspect`/endpoint state. `effort` remains a Claude-side
hint only: Switchboard validates and reports it but the local judge client does not consume it.
The `roles` pin table and its `claims` map are report-only in the same way: validated, surfaced by
`inspect --json` and the probe-free `inspect --roles --json` view, and never acted on.

## Update rule

When changing any config field, default, source path, validation boundary, or inspect state, update
this JSON fixture in the same change. `tests/test_config.py` and `tests/test_cli.py` compare the
fixture with runtime constants and report shapes, so an unpaired change fails CI.

## Consumer boundary

Switchboard owns config truth and bounded health facts. A consumer must not infer endpoint health,
successful model service, outcome evidence, certification, or call-site wiring from this fixture.
dev-observatory owns workspace caller/pin proof separately.
