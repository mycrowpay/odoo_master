# Deploy & Multi-tenant

## dbfilter
Set `DB_FILTER` env var to a regex that matches per-tenant DB names (e.g. `^trakka_.*$`). The Nginx layer should route per-tenant hostnames to the same Odoo, with `dbfilter = ^%d$` or a custom router if you use subdomains as DB names.

Example:



## Provisioning a new tenant
1. Create a new DB named `trakka_<slug>`.
2. Load base configs (company, currencies default KES, chart of accounts).
3. Install `trakka_ops` first (creates groups/menus), then `trakka_finops`, `trakka_returns`, `trakka_pulse`, `trakka_api`.
4. Configure Journals (FinOps module auto-creates if absent).
5. Configure API tokens for `trakka_api` (env or system parameter).
6. Configure MinIO/S3 integration in Gateway; in Odoo store only object keys.

## Backups
Use `pg_dump` per DB. Automate daily backups and test restore. Rotate secrets regularly.

## Upgrades
- Use module version bumps (`manifest['version']`).
- Migrations via `migrations/` folder per addon if needed.

