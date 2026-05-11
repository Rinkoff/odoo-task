from odoo import api,fields,models,_
from odoo.exceptions import ValidationError

class SaleBlanketOrder(models.Model):
    _name = "sale.blanket.order"
    _description = "Sale Blanket Order"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    name = fields.Char(
        string="Reference",
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Customer",
        required=True,
        tracking=True
    )
    validity_date_from = fields.Date(
        string="Start Date",
        required=True,
        default=fields.Date.context_today
    )
    validity_date_to = fields.Date(
        string="End Date",
        required=True
    )
    state = fields.Selection([
        ("draft", "Draft"),
        ("open", "Open"),
        ("expired", "Expired"),
        ("closed", "Closed"),
        ],
        string="Status",
        default="draft",
        tracking=True
    )
    line_ids = fields.One2many(
        "sale.blanket.order.line",
        "order_id",
        string="Order Lines",
        copy=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("name") or vals.get("name") == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("sale.blanket.order") or _("New")
        return super().create(vals_list)

    def action_confirm(self):
        self.write({"state": "open"})

    def action_close(self):
        self.write({"state": "closed"})


class SaleBlanketOrderLine(models.Model):
    _name = "sale.blanket.order.line"
    _description = "Sale Blanket Order Line"

    order_id = fields.Many2one(
        "sale.blanket.order",
        string="Blanket Order",
        ondelete="cascade",
        required=True
    )
    product_id = fields.Many2one(
        "product.product",
        string="Product",
        required=True
    )
    price_unit = fields.Float(
        string="Agreed Price",
        required=True
    )
    qty_total = fields.Float(
        string="Total Quantity",
        required=True
    )
    qty_delivered = fields.Float(
        string="Delivered Quantity",
        compute="_compute_qty_delivered",
        store=True
    )
    qty_remaining = fields.Float(
        string="Remaining Quantity",
        compute="_compute_qty_remaining",
        store=True
    )

    sale_line_ids = fields.One2many(
        "sale.order.line",
        "blanket_line_id",
        string="Sale Order Lines"
    )

    @api.depends("sale_line_ids.product_uom_qty", "sale_line_ids.state")
    def _compute_qty_delivered(self):
        for line in self:
            lines = line.sale_line_ids.filtered(lambda l: l.state in ("draft", "sent", "sale", "done"))
            line.qty_delivered = sum(lines.mapped('product_uom_qty'))

    @api.depends('qty_total', 'qty_delivered')
    def _compute_qty_remaining(self):
        for line in self:
            line.qty_remaining = line.qty_total - line.qty_delivered


