from odoo import models, fields, api, _


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def write(self, vals):
        res = super(SaleOrder, self).write(vals)

        if not self.env.context.get("skip_blanket_apply"):
            if "order_line" in vals or "partner_id" in vals:
                for order in self:
                    order._apply_blanket_orders()
        return res

    @api.model_create_multi
    def create(self, vals_list):
        orders = super(SaleOrder, self).create(vals_list)
        for order in orders:
            if not self.env.context.get("skip_blanket_apply"):
                order._apply_blanket_orders()
        return orders

    def _apply_blanket_orders(self):
        self.ensure_one()
        today = fields.Date.context_today(self)

        # 1. Identify product lines to process
        # We only process real products, not sections/notes
        lines_to_process = self.order_line.filtered(lambda l: l.product_id and not l.display_type)

        if not lines_to_process:
            return

        # We group total demand per product to redistribute it
        product_demands = {}
        for line in lines_to_process:
            product_demands.setdefault(line.product_id, 0.0)
            product_demands[line.product_id] += line.product_uom_qty

        for product, total_needed in product_demands.items():
            # 2. Find valid Blanket Orders for this product and partner
            # Valid = Open, not expired, same partner, remaining qty > 0
            bo_lines = self.env["sale.blanket.order.line"].search([
                ("order_id.partner_id", "=", self.partner_id.id),
                ("order_id.state", "=", "open"),
                ("order_id.validity_date_from", "<=", today),
                ("order_id.validity_date_to", ">=", today),
                ("product_id", "=", product.id),
                ("qty_remaining", ">", 0),
            ], order="order_id.validity_date_from asc, id asc")

            # Calculate distribution
            remaining_to_distribute = total_needed
            new_distribution = []

            for bo_line in bo_lines:
                if remaining_to_distribute <= 0:
                    break

                # We need to consider that other lines in THIS order might already be linked
                # but qty_remaining might not be updated yet if it's stored.
                # However, for simplicity and following the task logic, we use available qty.
                take = min(remaining_to_distribute, bo_line.qty_remaining)
                if take > 0:
                    new_distribution.append({
                        "qty": take,
                        "price": bo_line.price_unit,
                        "blanket_line_id": bo_line.id
                    })
                    remaining_to_distribute -= take

            # 3. Handle leftover with pricelist
            if remaining_to_distribute > 0:
                # Use standard Odoo price fetching
                price = self.pricelist_id._get_product_price(product, remaining_to_distribute, self.partner_id)
                new_distribution.append({
                    "qty": remaining_to_distribute,
                    "price": price,
                    "blanket_line_id": False
                })

            # 4. Sync current lines with new distribution
            existing_product_lines = lines_to_process.filtered(lambda l: l.product_id == product)

            idx = 0
            for dist in new_distribution:
                vals = {
                    "product_uom_qty": dist["qty"],
                    "price_unit": dist["price"],
                    "blanket_line_id": dist["blanket_line_id"],
                }
                if idx < len(existing_product_lines):
                    # Update existing line
                    existing_product_lines[idx].with_context(skip_blanket_apply=True).write(vals)
                else:
                    # Create new line
                    self.env["sale.order.line"].with_context(skip_blanket_apply=True).create({
                        "order_id": self.id,
                        "product_id": product.id,
                        **vals
                    })
                idx += 1

            # Remove redundant lines if we have fewer segments now
            if idx < len(existing_product_lines):
                existing_product_lines[idx:].with_context(skip_blanket_apply=True).unlink()


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    blanket_line_id = fields.Many2one(
        "sale.blanket.order.line",
        string='Blanket Order Line',
        readonly=True,
        copy=False
    )

    # We override the qty_delivered compute trigger in the BO Line model
    # but we can also ensure that when a line is deleted, we re-apply logic
    def unlink(self):
        orders = self.mapped("order_id")
        res = super(SaleOrderLine, self).unlink()
        for order in orders:
            if not self.env.context.get("skip_blanket_apply"):
                order._apply_blanket_orders()
        return res
