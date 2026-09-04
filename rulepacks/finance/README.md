# Financial-services rule pack

Red zones and risk factors for the AI patterns most enterprise
financial-services AI policies call out by name: credit and underwriting
decisions, AML/sanctions screening, algorithmic trading, retail investment
advice, and third-party handling of cardholder or account data.

Framework refs (`ECOA`, `FCRA`, `DORA`, `APRA:CPS230`/`CPS234`, `PCI-DSS`,
`SOC2`, `SR-11-7`, `SEC`, `FINRA`) are informational mappings, not compliance
claims — see the disclaimer in the repo's [CONTRIBUTING.md](../../CONTRIBUTING.md).
Calibrate the weights, tiers, and the `finance.*` vocabulary below to your own
policy and risk appetite; the shape is the point.

## Vocabulary

This pack reads the `finance.*` namespace in the intake context, alongside
the shared `use_case.*`, `data.*`, `model.*`, `oversight.*`, `agent.*`, and
`observability.*` namespaces documented in [docs/schema.md](../../docs/schema.md).

| Path | Type | Meaning |
|---|---|---|
| `finance.decision_type` | string | One of `credit_decisioning`, `underwriting`, `aml_screening`, `algorithmic_trading`, `robo_advice`, `fraud_detection`, `collections`, `kyc`. |
| `finance.adverse_action_explainable` | bool | The system can produce the specific, individualized reason for a credit/underwriting denial (not just a score band). |
| `finance.auto_dismiss_alerts` | bool | AML/sanctions alerts are closed as false positives by the model with no analyst disposition. |
| `finance.kill_switch` | bool | A human-operable kill switch exists for the trading strategy. |
| `finance.pre_trade_risk_controls` | bool | Position/notional limits and fat-finger checks run before an order reaches the market. |
| `finance.suitability_disclosure_shown` | bool | The retail customer sees the suitability / best-interest disclosure for automated advice. |
| `finance.licensed_advisor_review` | bool | A licensed advisor sits in the oversight chain for the advice given. |
| `finance.third_party_data_agreement_signed` | bool | A signed data-processing / sub-processor agreement covers the AI vendor for cardholder or account data. |
| `finance.pci_scope_assessed` | bool | The data flow into the AI vendor has been through a PCI DSS scope assessment. |
| `finance.model_risk_validated` | bool | Independent model validation (not by the build team) has signed off on the model. |
| `finance.cross_border_data_transfer` | bool | The use case moves data across a jurisdictional boundary. |
| `finance.moves_funds` | bool | The system can initiate or move customer funds without a person triggering each transfer. |

`data.categories` gains two finance-specific values used by this pack:
`cardholder_data` and `credit_report_data` (alongside the shared
`personal_data`, `sensitive_personal_data`, and `financial_records`).

## Composition

```bash
hashimori evaluate --rules rulepacks/red-zone rulepacks/finance --context your-intake.json
hashimori test examples/tests/finance-decisions.yaml --rules rulepacks/red-zone rulepacks/finance
```

Compose this pack with **`rulepacks/red-zone`** (the universal "never" list —
still worth checking first) but **not** with `rulepacks/baseline`. Hashimori's
tier selection walks every loaded pack's tiers in pack-load order and stops at
the first tier whose `max_score` isn't exceeded; `baseline`'s catch-all
`elevated_review` tier (no `max_score`) would win before `finance`'s tiers are
ever reached, and `baseline`'s risk factors would report `finance.*` paths as
unknown on every context that doesn't set them — silently blocking
auto-approval. Keep industry packs on their own, load-scoped to `red-zone`.

## Tests

[`examples/tests/finance-decisions.yaml`](../../examples/tests/finance-decisions.yaml)
exercises all six red zones plus the fail-closed path on a vague submission.
`tests/test_finance_pack.py` runs the same pack through pytest, scoped
separately from `tests/test_engine.py` for the reason above.
