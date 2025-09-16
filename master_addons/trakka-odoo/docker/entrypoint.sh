#!/usr/bin/env bash
set -euo pipefail

export PYTHONUNBUFFERED=1

# Render env vars into config (handled by docker-compose bind)
exec odoo -c /etc/odoo/odoo.conf
