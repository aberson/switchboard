# Remaining-work estimates

Forward remaining effort in hours, including implementation and its checks/review. Operator attention is separate. Elapsed waits, service quotas and hardware availability are not labor. These are model forecasts, not measured history. Held rows remain disabled.

Rows validate as ForecastEstimate. Portable worksheet only: production ForecastConfig is currently restricted to dev-observatory and 100 estimates; no saved forecast was modified.

Plan: [master_plan.md](master_plan.md). SHA-256: `afb937aaf71f1593b8d6b600ed2c1b809e93034e773921bd70091dece01465a9`.

Rebind after editing the plan; source fingerprints deliberately become stale. The JSON preserves dependencies and evidence locations.

| Step | Worker hours | Attention hours | Confidence | Availability | Basis |
|---|---:|---:|---:|---|---|
| B3 — B2b — Live certify-and-enable smoke (operator) | 0.4–1.0 | 0.5–1.5 | 0.35 | enabled forecast | Inspect config, certify, enable only qualified style slice and demonstrate surgical kill; preparation gap remains held. |
| O74 — Real routing UAT | 0.15–0.4 | 0.4–1.0 | 0.35 | enabled forecast | Exercise inspect/config, recorded bakeoff, launcher policy separation and real routing evidence. |
| P7 — Operator UAT + open the PR(s) | 0.5–1.5 | 1.0–2.5 | 0.35 | enabled forecast | External browser acceptance and two independent feature branches; publication needs owner workflow. |
| T1 — Scaffold `switchboard-tune` and mine real judge inputs | 4.0–8.0 | 0.2–0.5 | 0.35 | enabled forecast | Mine real deduplicated small source hunks and scaffold shared prompt identity. |
| T2 — Mint teacher labels with Claude and freeze the golden set | 4.0–8.0 | 0.5–1.5 | 0.35 | enabled forecast | Teacher subprocess receipts, freeze split hashes and cross-split near-duplicate guard; paid/runtime waiting separate. |
| T3 — Eval harness with calibration anchors and the zero-dep guard | 4.0–8.0 | 0.2–0.5 | 0.35 | enabled forecast | Strict/coverage/agreement scoring, calibration anchors and zero-dependency guard. |
| T4 — End-to-end smoke gate — 20 rows, 10 steps, one real verdict | 5.0–10.0 | 0.4–1.0 | 0.35 | enabled forecast | Real 20-row training-to-GGUF-to-runtime smoke plus sentinel and chat-template parity. |
| T5 — Baseline — score the untuned student through the shipped runtime | 2.0–4.0 | 0.2–0.5 | 0.35 | enabled forecast | Reproduce untuned baseline twice under identical runtime/quant and fixed manifest. |
| T6 — Full QLoRA SFT run | 3.0–6.0 | 0.25–0.75 | 0.35 | enabled forecast | Masked-prompt QLoRA training and dev checkpoint selection; GPU wall time separate. |
| T7 — Eval the tuned student and write the honest comparison | 3.0–6.0 | 0.3–0.8 | 0.35 | enabled forecast | Compare held-out results, persist disagreement pairs and four-part honest negative analysis. |
| T8 — Ship script — place, certify, and report | 3.0–6.0 | 0.2–0.5 | 0.35 | enabled forecast | Dry-run artifact placement, config checks and certification reporting without enablement. |
| T9 — Live certify and enable decision (operator) | 0.3–0.8 | 0.6–1.5 | 0.35 | enabled forecast | Operator independently certifies and decides enable/do-not-enable only style slice. |
| T10 — Optional DPO stretch | 5.0–10.0 | 0.3–0.8 | 0.35 | enabled forecast | Conditional DPO training/eval only after at least 100 valid disagreement pairs. |
