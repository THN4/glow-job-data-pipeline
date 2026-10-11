# Shared components

`src.shared` contains only adapters and utilities that multiple domains can
reuse. It should not contain market-only business rules or resume/document
workflow orchestration.

| Package | Responsibility |
|---|---|
| `skill_normalization` | Normalize skill-name forms, resolve canonical names and confirmed aliases, and preserve unmatched names for the caller to review. |
| `llm` | Provider clients, credentials, request handling, and shared retry behavior. Domain prompts and response contracts stay with each domain. |
| `db` | Generic PostgreSQL connection and transaction setup. Domain-specific SQL and repositories stay in `market`, `resume`, or `documents`. |
| `utils` | Small helpers that do not depend on one domain's data model. |
| `schemas` | Data contracts that are genuinely shared across domains. |

Before adding a helper here, confirm that more than one domain can use it
without adopting the market domain's assumptions.
