# Seed: Observatory roles/pins producer artifact

**Status:** queued (operator, 2026-11-17: "Queue it"). Not started; no lane. Build when switchboard work resumes (Phase R-B onward waits on the Toolkit program selection, U04).
**Requested by:** dev-observatory main for its Step 39b (switchboard rich surfaces), note `20261117T215204Z-main-to-main-ce50`.

## What is asked

One explicit, durable producer artifact written by switchboard, which Observatory reads and never generates:

- **Path:** a fixed location such as `switchboard/.observatory/roles.json`.
- **Envelope:** the Observatory generic envelope: a schema id and an ISO-8601 UTC `generated_at`, with `explorer.v1` items carrying route-safe `id`, `label`, `summary` and `detail`.
- **Content:** per role, the pinned model per host, what the role is for, and the config locator (file and line) that proves the pin.
- **Fold in, if it fits:** requested vs observed dispatch from `docs/seeds/seed_dispatch_proof.md`, and the O73 bake-off output path, so there is one producer artifact rather than several.
- **Generation:** an explicit switchboard export command. Observatory never runs a producer from a scan, GET or export of its own.

## Constraints

- Observatory's consumer is built only after this contract lands; dev-observatory builds nothing that depends on it before then.
- dev-observatory Step 39a (a contract-drift gate on the switchboard panel against `docs/observatory-contract.json`) proceeds without switchboard changes.
- The artifact carries no secrets and no home paths; locators are repository-relative.

## When it is picked up

Turn this into a `### Step` in `docs/plans/master_plan.md` through the normal plan flow (plan-feature or plan-review), with an issue, then build it. Tell dev-observatory main when the contract lands.
