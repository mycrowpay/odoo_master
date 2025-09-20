# Trakka FinOps

Escrow lifecycle, seller wallet and nightly settlements.

- Escrow states: `held → released_ready → released`.
- Settlement job posts Dr Escrow Liability / Cr Seller Wallet and credits Wallet.
- Wallet moves are idempotent via `idempotency_key` (unique).
- Journals created: ESC (Escrow Liability), WLT (Seller Wallet), BPL (Buyer Payout Liability), RHR (Returns Handling Revenue).

**Dependencies:** base, sale, account, stock, trakka_ops.

**Cron:** `trakka_finops.cron_nightly_settlement` runs nightly at 02:00 server time.
