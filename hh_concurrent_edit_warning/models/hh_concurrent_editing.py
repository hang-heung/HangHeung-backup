from odoo import api, fields, models

# Models whose form views show the banner. The frontend widget is restricted
# to these via view inheritance, but we also guard on the server to refuse
# heartbeats for any other model so this table can't be used as a
# general-purpose presence service.
TRACKED_MODELS = ("sale.order", "purchase.order", "stock.picking")

# A heartbeat older than STALE_SECONDS means the editor has gone away
# (closed tab, lost network, browser crash). Frontend heartbeats every 15s,
# so 60s gives a 4x grace.
STALE_SECONDS = 60


class HHConcurrentEditing(models.Model):
    _name = "hh.concurrent.editing"
    _description = "Active editor presence record for soft-lock banners"
    _rec_name = "res_id"

    model_name = fields.Char(required=True, index=True)
    res_id = fields.Integer(required=True, index=True)
    user_id = fields.Many2one("res.users", required=True, ondelete="cascade", index=True)
    last_heartbeat = fields.Datetime(required=True, default=fields.Datetime.now)

    _sql_constraints = [
        (
            "uniq_user_record",
            "unique(model_name, res_id, user_id)",
            "Only one presence row per (record, user).",
        ),
    ]

    # ------------------------------------------------------------------
    # Bus channel helpers
    # ------------------------------------------------------------------
    @api.model
    def _channel(self, model_name, res_id):
        """Bus channel string for a given record. Anyone subscribed
        receives presence-change notifications."""
        return f"hh.editing:{model_name}:{res_id}"

    @api.model
    def _notify_change(self, model_name, res_id):
        """Broadcast a refresh hint to all subscribers of this record's
        channel. Payload is intentionally small -- clients call back to
        get the authoritative editor list."""
        self.env["bus.bus"]._sendone(
            self._channel(model_name, res_id),
            "hh.editing/refresh",
            {"model": model_name, "res_id": res_id},
        )

    # ------------------------------------------------------------------
    # Public RPC API (called by the frontend widget)
    # ------------------------------------------------------------------
    @api.model
    def hh_register(self, model_name, res_id):
        """Mark the current user as actively editing (model, res_id).
        Idempotent: a second call from the same user just bumps the
        heartbeat. Broadcasts presence change."""
        if model_name not in TRACKED_MODELS or not res_id:
            return False
        now = fields.Datetime.now()
        existing = self.sudo().search([
            ("model_name", "=", model_name),
            ("res_id", "=", res_id),
            ("user_id", "=", self.env.uid),
        ], limit=1)
        if existing:
            existing.last_heartbeat = now
        else:
            self.sudo().create({
                "model_name": model_name,
                "res_id": res_id,
                "user_id": self.env.uid,
                "last_heartbeat": now,
            })
        self._notify_change(model_name, res_id)
        return True

    @api.model
    def hh_heartbeat(self, model_name, res_id):
        """Bump last_heartbeat for the current user's presence row.
        Does NOT broadcast -- presence updates are silent; only
        enter/leave events ping other clients."""
        if model_name not in TRACKED_MODELS or not res_id:
            return False
        row = self.sudo().search([
            ("model_name", "=", model_name),
            ("res_id", "=", res_id),
            ("user_id", "=", self.env.uid),
        ], limit=1)
        if row:
            row.last_heartbeat = fields.Datetime.now()
            return True
        # Lost our row (e.g. cron pruned it). Recreate via register.
        return self.hh_register(model_name, res_id)

    @api.model
    def hh_unregister(self, model_name, res_id):
        """Remove the current user's presence row. Called on form
        close / page unload. Broadcasts so other clients drop the
        banner immediately."""
        if model_name not in TRACKED_MODELS or not res_id:
            return False
        rows = self.sudo().search([
            ("model_name", "=", model_name),
            ("res_id", "=", res_id),
            ("user_id", "=", self.env.uid),
        ])
        if rows:
            rows.unlink()
            self._notify_change(model_name, res_id)
        return True

    @api.model
    def hh_get_editors(self, model_name, res_id):
        """Return the list of OTHER users currently editing this record.
        Filters out the caller and any stale heartbeats."""
        if model_name not in TRACKED_MODELS or not res_id:
            return []
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), seconds=STALE_SECONDS)
        rows = self.sudo().search([
            ("model_name", "=", model_name),
            ("res_id", "=", res_id),
            ("user_id", "!=", self.env.uid),
            ("last_heartbeat", ">=", cutoff),
        ])
        now = fields.Datetime.now()
        return [
            {
                "user_id": r.user_id.id,
                "user_name": r.user_id.name,
                "seconds_ago": int((now - r.last_heartbeat).total_seconds()),
            }
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------
    @api.model
    def _cron_prune_stale(self):
        """Daily defensive cleanup of presence rows that outlived their
        editor (e.g. browser crashed without firing beforeunload). The
        frontend already ignores stale rows via the cutoff in
        hh_get_editors, this just keeps the table from growing."""
        cutoff = fields.Datetime.subtract(fields.Datetime.now(), seconds=STALE_SECONDS * 60)
        self.sudo().search([("last_heartbeat", "<", cutoff)]).unlink()
