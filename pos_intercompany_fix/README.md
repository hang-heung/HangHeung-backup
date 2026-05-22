# pos_intercompany_fix

Fixes the `stock.picking` access error that occurs in Odoo 18 POS when a cashier
processes orders containing products with inter-company stock routes.

## Problem

Employee ST1 (company: Hoymay HK Ltd, company_id=1) receives:

> 員工ST1 (id=47) 對下列項目沒有「讀取」權限：- 轉移 (stock.picking)

This happens because product H0500101000 (金裝龍鳳餅) has routes belonging to
That's Ltd (company_id=2) and Hang Heung Cake Shop (company_id=3). The multi-company
record rule on `stock.picking` blocks ST1 from reading cross-company pickings during
procurement traversal.

## Fix

Overrides `_create_order_picking()` in `pos.order` to run in `sudo()` context,
allowing the procurement engine to traverse all inter-company routes.

**No user-facing permissions are changed. No database schema changes.**

Reference: https://github.com/odoo/odoo/issues/22774

## Install

1. Copy this module to your custom addons path:
   ```bash
   sudo cp -r pos_intercompany_fix /opt/odoo18/odoo18/custom-addons/
   sudo chown -R odoo18:odoo18 /opt/odoo18/odoo18/custom-addons/pos_intercompany_fix
   ```

2. Restart Odoo to pick up the new module:
   ```bash
   sudo systemctl restart odoo18
   ```

3. Install via Odoo UI:
   - Go to **Settings → Apps → Update App List**
   - Search for `POS Inter-Company Picking Fix`
   - Click **Install**

   Or install via CLI (replace `your_db` with your database name):
   ```bash
   sudo -u odoo18 /opt/odoo18/odoo18-venv/bin/python /opt/odoo18/odoo18/odoo-bin \
       -c /etc/odoo18.conf \
       -d your_db \
       -i pos_intercompany_fix \
       --stop-after-init
   ```

## Uninstall / Revert

To fully revert, uninstall the module from the Odoo UI:
- Go to **Settings → Apps**
- Search for `POS Inter-Company Picking Fix`
- Click **Uninstall**

Then restart Odoo:
```bash
sudo systemctl restart odoo18
```

Optionally remove the files:
```bash
sudo rm -rf /opt/odoo18/odoo18/custom-addons/pos_intercompany_fix
```
