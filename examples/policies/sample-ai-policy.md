# Auroria Systems — AI Acceptable Use & Governance Policy (v2.3)

*Auroria Systems is a fictional company. This document exists so you can watch
the `policy-to-rules` skill convert a realistic policy into a Hashimori pack —
compare it with `rulepacks/` to see the mapping.*

## 1. Purpose

This policy governs the development and deployment of AI systems at Auroria
Systems. All AI use cases must be submitted through the AI intake process and
receive a governance decision before deployment.

## 2. Prohibited uses

The following are prohibited under all circumstances and will not be granted
exceptions:

2.1 AI systems that make final decisions affecting an individual's access to
credit, employment, housing, insurance, medical care, legal outcomes, or
education without a qualified human reviewing and approving each decision
before it takes effect.

2.2 Transmission of sensitive personal data (health, biometric, financial
account, or children's data) to any model provider that has not completed
Auroria's provider security assessment.

2.3 Inference of employees' emotional states or biometric categorization of
employees, regardless of stated purpose.

2.4 Scoring or ranking of individuals' trustworthiness based on social or
behavioral signals unrelated to the service being provided.

2.5 Autonomous agents that can take irreversible actions (financial
transactions, data deletion, production configuration changes) without both a
pre-action approval gate and a tested rollback plan.

2.6 Use of customer data for model training or fine-tuning without a
documented legal basis reviewed by counsel.

## 3. Risk-based review

Use cases that are not prohibited are assessed on cumulative risk. Elevated
scrutiny applies to systems that: process personal data; are customer- or
public-facing; take autonomous actions; affect large populations; use
providers new to Auroria; lack output logging; or influence what content
people see at scale.

## 4. Approval tiers

- **Fast track.** Low-risk use cases are approved automatically, subject to
  standing obligations: output logging, registration in the AI inventory, and
  annual re-review.
- **Standard review.** Moderate-risk use cases are reviewed by Security
  within 5 business days.
- **Elevated review.** High-risk use cases are reviewed by Security, Privacy,
  Legal, and the AI Governance Board within 15 business days.

## 5. Intake honesty

Submitting teams are responsible for the accuracy of intake information.
Incomplete submissions will not be auto-approved. Misrepresentation of a
system's autonomy, data flows, or oversight controls is a policy violation.

## 6. Records

All governance decisions, including automated ones, are retained with the
rule versions and intake data that produced them, sufficient to reproduce the
decision in an audit.
