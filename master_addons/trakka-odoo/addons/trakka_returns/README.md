# Trakka Returns OS

Data-driven returns orchestration:
- Policy presets (Standard, Friendly, Strict) + per-category overrides
- Return Case decisions (who pays shipping, handling fee, restocking, refund math)
- Reverse picking creation
- Credit note posting
- Accounting for refunds via Escrow or Seller Wallet (Buyer Payout Liability)

**Notes**
- Evidence media are NOT stored in DB; only S3/MinIO object keys are in `evidence_keys` (JSON).
- `evidence_url_placeholders` provides placeholders where a Gateway can inject pre-signed GET URLs.

**Security**
- Uses Trakka ops/finance/admin groups from `trakka_ops`.
- Record rules ensure no cross-company leakage (multi-tenant per DB).

**Tests**
- See `tests/test_returns.py`.
