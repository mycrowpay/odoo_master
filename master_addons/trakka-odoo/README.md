# Trakka Odoo 17 Backend (Multi-tenant)

This repo contains five Odoo 17 addons powering Trakka's Delivery Assurance platform:
- `trakka_finops`: Escrow, Wallet, Settlements
- `trakka_returns`: Returns OS
- `trakka_pulse`: Rider telemetry records
- `trakka_api`: Private JSON endpoints (Gateway/BFF only)
- `trakka_ops`: Ops Console, app shell, security groups

## Stack
- Odoo Community 17
- PostgreSQL 16
- Python 3.10+
- Docker Compose

## Quick start
1. Copy `.env.example` to `.env` and adjust values.
2. `docker compose up -d --build`
3. Visit `http://localhost:8069` and create a database for a tenant.
4. Install addons from the Apps menu (search "Trakka"). Order: `trakka_ops` → others.

See `DEPLOY.md` for dbfilter multi-tenant details.
