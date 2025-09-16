# Security

- Private Odoo: Never expose /web to public users. Gateway/BFF authenticates clients and talks to Odoo via private network.
- Controllers: `trakka_api` requires Bearer JWT + Idempotency-Key. No public endpoints.
- Groups:
  - trakka_group_admin
  - trakka_group_finance
  - trakka_group_ops
  - trakka_group_support
  - trakka_group_readonly
- Record rules: ensure no cross-tenant leakage (Odoo multi-DB already isolates; add future per-company rules if needed).
- Logging: structured logs around money mutations (FinOps).
- Secrets rotation: use env vars for tokens/keys; rotate periodically.
