# -*- coding: utf-8 -*-

from itertools import groupby
from odoo import api, fields, models, _
from odoo.exceptions import UserError, AccessError
from odoo.tools.float_utils import float_round
import base64
import time
import requests
import json
import logging
_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = "sale.order"

    marketplace_vendor_line = fields.One2many('marketplace.vendor', 'sale_order')
    marketplace_vendor_line_total = fields.One2many('marketplace.vendor.total', 'sale_order')

    @api.model
    def create(self, vals):
        result = super(SaleOrder, self).create(vals)
        if result.warehouse_id:
            if not result.warehouse_id.code:
                raise UserError(_('Debe colocar el Codigo del local %s', result.warehouse_id.name))
            if not result.warehouse_id.country_id:
                raise UserError(_('Debe colocar el pais del local %s', result.warehouse_id.name))
            if not result.warehouse_id.state_id:
                raise UserError(_('Debe colocar la Provincia del local %s', result.warehouse_id.name))
            if not result.warehouse_id.country_id.code_mini:
                raise UserError(_('Debe colocar el Código MiniGO al pais del local %s', result.warehouse_id.name))
            if not result.warehouse_id.state_id.code_mini:
                raise UserError(_('Debe colocar el Código MiniGO a la Provincia del local %s', result.warehouse_id.name))
            result.name = (result.warehouse_id.country_id.code_mini + '-' + result.warehouse_id.state_id.code_mini
                           + '-' + result.warehouse_id.code + '-' + result.name)
        result.create_marketplace_vendor()
        return result

    def write(self, vals):
        res = super(SaleOrder, self).write(vals)
        self.create_marketplace_vendor()
        return res

    def create_marketplace_vendor(self):
        count_amount = 0
        cont = 0
        for marketplace_vendor in self.marketplace_vendor_line:
            marketplace_vendor.unlink()
        for marketplace_vendor_total in self.marketplace_vendor_line_total:
            marketplace_vendor_total.unlink()
        for line in self.sudo().order_line:
            discount = 0
            price_unit = 0
            tax_line = []
            sale_percentage_go = (100 - line.seller.commission)
            amount_commission = (line.price_subtotal * (sale_percentage_go/100))
            amount_tax_company = line.company_id.sudo().account_sale_tax_id.amount
            amount_tax_company_total = (amount_commission * (amount_tax_company/100))
            amount_commission_amount_tax_company_total = amount_commission + amount_tax_company_total
            total_tax = 0
            total_int = 0
            for tax in line.tax_id:
                tax_line.append((4, tax.id))
                iva = tax.amount / 100
                if tax.marketplace_type == 'iva':
                    total_tax += line.price_subtotal * iva
                if tax.marketplace_type == 'int':
                    total_int += line.price_subtotal * iva
            if line.discount:
                discount = line.discount / 100
                price_unit = (line.price_unit - (line.price_unit * discount))
            else:
                price_unit = line.price_unit
            cont += 1
            valor = self.env['ir.config_parameter'].sudo().get_param('marketplace_vendor_code.code')
            vals = {
                'code': self.env['ir.config_parameter'].sudo().get_param('marketplace_vendor_code.code') + '-' + str(cont),
                'sale_order': self.id,
                'sale_order_line': line.id,
                'name': line.seller.id,
                'product_template_id': line.product_template_id.id,
                'product_id': line.product_id.id,
                'price_unit': line.price_unit,
                'amount_tax': line.price_tax,
                'price_subtotal': line.price_subtotal,
                'sale_percentage_vendor': line.seller.commission,
                'sale_percentage_go': sale_percentage_go,
                'amount_commission': amount_commission,
                'amount_tax_company': line.company_id.sudo().account_sale_tax_id.amount,
                'amount_tax_company_total': amount_tax_company_total,
                'amount_commission_amount_tax_company_total': amount_commission_amount_tax_company_total,
                'total_vendor': (price_unit * line.product_uom_qty) - amount_commission_amount_tax_company_total,
                'tax_id': tax_line,
                'total_tax': total_tax,
                'total_int': total_int,
                'partner_id': self.partner_id.id,
                'discount': line.discount if line.discount else 0,
                'discount_unit': ((line.discount * line.price_unit)/100) if line.discount else 0,
                'discount_total': line.price_unit - ((line.discount * line.price_unit)/100) if line.discount else 0
            }
            total_vendor = (price_unit * line.product_uom_qty) - amount_commission_amount_tax_company_total
            self.sudo().marketplace_vendor_line.create(vals)
            count_amount += amount_commission_amount_tax_company_total
            if self.marketplace_vendor_line_total:
                vendor_exist = False
                for rec in self.marketplace_vendor_line_total.filtered(lambda x: x.vendor == line.seller):
                    rec.total += total_vendor
                    vendor_exist = True
                if not vendor_exist:
                    self.sudo().marketplace_vendor_line_total.create({
                        'sale_order': self.id,
                        'name': line.seller.name,
                        'vendor': line.seller.id,
                        'total': total_vendor
                    })
            else:
                self.sudo().marketplace_vendor_line_total.create({
                    'sale_order': self.id,
                    'name': line.seller.name,
                    'vendor': line.seller.id,
                    'total': total_vendor
                })
        if self.marketplace_vendor_line_total:
            self.sudo().marketplace_vendor_line_total.create({
                'sale_order': self.id,
                'name': self.company_id.partner_id.name,
                'vendor': self.company_id.partner_id.id,
                'total': count_amount,
                'date': fields.Datetime.now(),
            })

    def _invoice_lines_by_seller(self, order_lines):
        seller_lines = []
        lines = []
        down_payment_line = []
        sellers = {}
        position = 0
        for line in order_lines:
            if line.display_type in ['line_section', 'line_note']:
                down_payment_line.append(line.id)
            else:
                if str(line.seller.id) not in sellers:
                    sellers[str(line.seller.id)] = position
                    lines.append([line.id])
                    position += 1
                else:
                    lines[sellers[str(line.seller.id)]].append(line.id)

        for partner_line in lines:
            seller_lines.append(self.env['sale.order.line'].browse(partner_line + down_payment_line))
        return seller_lines

    def action_confirm(self):
        res = super(SaleOrder, self).action_confirm()
        if res:
            for picking in self.picking_ids:
                if picking.state in ['assigned']:
                    for move in picking.move_lines.filtered(lambda m: m.state not in ['done', 'cancel']):
                        for move_line in move.move_line_ids:
                            move_line.qty_done = move_line.product_uom_qty
                    picking.with_context(skip_immediate=True, skip_backorder=True, skip_sms=True).button_validate()
            moves = self._create_invoices()
        return res

    def _get_invoice_grouping_keys(self):
        return ['company_id', 'seller_id', 'currency_id']

    def _create_invoices(self, grouped=False, final=False, date=None):
        if not self.env['account.move'].check_access_rights('create', False):
            try:
                self.check_access_rights('write')
                self.check_access_rule('write')
            except AccessError:
                return self.env['account.move']

        # 1) Create invoices.
        invoice_vals_list = []
        invoice_item_sequence = 0 # Incremental sequencing to keep the lines order on the invoice.
        for order in self:
            order = order.with_company(order.company_id)
            current_section_vals = None
            down_payments = order.env['sale.order.line']

            invoice_values = order._prepare_invoice()
            invoiceable_lines = order._get_invoiceable_lines(final)

            if not any(not line.display_type for line in invoiceable_lines):
                raise self._nothing_to_invoice_error()

            seller_lines = self._invoice_lines_by_seller(invoiceable_lines)

            for seller_line in seller_lines:
                invoice_vals = invoice_values.copy()
                invoice_line_vals = []
                down_payment_section_added = False
                seller_id = 0
                for line in seller_line:
                    if not down_payment_section_added and line.is_downpayment:
                        # Create a dedicated section for the down payments
                        # (put at the end of the invoiceable_lines)
                        invoice_line_vals.append(
                            (0, 0, order._prepare_down_payment_section_line(
                                sequence=invoice_item_sequence,
                            )),
                        )
                        dp_section = True
                        invoice_item_sequence += 1
                    invoice_line_vals.append(
                        (0, 0, line._prepare_invoice_line(
                            sequence=invoice_item_sequence,
                        )),
                    )
                    invoice_item_sequence += 1
                    seller_id = line.seller.id
                    electronic_invoice_type = line.seller.electronic_invoice_type
                    narration = line.seller.invoices_note

                invoice_vals['seller_id'] = seller_id
                invoice_vals['warehouse_id'] = order.warehouse_id.id
                invoice_vals['electronic_invoice_type'] = electronic_invoice_type
                invoice_vals['narration'] = narration or ''
                invoice_vals['invoice_line_ids'] = invoice_line_vals
                invoice_vals_list.append(invoice_vals)

        if not invoice_vals_list:
            raise self._nothing_to_invoice_error()

        # 2) Manage 'grouped' parameter: group by (partner_id, currency_id).
        if not grouped:
            new_invoice_vals_list = []
            invoice_grouping_keys = self._get_invoice_grouping_keys()
            for grouping_keys, invoices in groupby(invoice_vals_list, key=lambda x: [x.get(grouping_key) for grouping_key in invoice_grouping_keys]):
                origins = set()
                payment_refs = set()
                refs = set()
                ref_invoice_vals = None
                for invoice_vals in invoices:
                    if not ref_invoice_vals:
                        ref_invoice_vals = invoice_vals
                    else:
                        ref_invoice_vals['invoice_line_ids'] += invoice_vals['invoice_line_ids']
                    origins.add(invoice_vals['invoice_origin'])
                    payment_refs.add(invoice_vals['payment_reference'])
                    refs.add(invoice_vals['ref'])
                ref_invoice_vals.update({
                    'ref': ', '.join(refs)[:2000],
                    'invoice_origin': ', '.join(origins),
                    'payment_reference': len(payment_refs) == 1 and payment_refs.pop() or False,
                })
                new_invoice_vals_list.append(ref_invoice_vals)
            invoice_vals_list = new_invoice_vals_list

        # 3) Create invoices.

        # As part of the invoice creation, we make sure the sequence of multiple SO do not interfere
        # in a single invoice. Example:
        # SO 1:
        # - Section A (sequence: 10)
        # - Product A (sequence: 11)
        # SO 2:
        # - Section B (sequence: 10)
        # - Product B (sequence: 11)
        #
        # If SO 1 & 2 are grouped in the same invoice, the result will be:
        # - Section A (sequence: 10)
        # - Section B (sequence: 10)
        # - Product A (sequence: 11)
        # - Product B (sequence: 11)
        #
        # Resequencing should be safe, however we resequence only if there are less invoices than
        # orders, meaning a grouping might have been done. This could also mean that only a part
        # of the selected SO are invoiceable, but resequencing in this case shouldn't be an issue.
        if len(invoice_vals_list) < len(self):
            SaleOrderLine = self.env['sale.order.line']
            for invoice in invoice_vals_list:
                sequence = 1
                for line in invoice['invoice_line_ids']:
                    line[2]['sequence'] = SaleOrderLine._get_invoice_line_sequence(new=sequence, old=line[2]['sequence'])
                    sequence += 1

        # Manage the creation of invoices in sudo because a salesperson must be able to generate an invoice from a
        # sale order without "billing" access rights. However, he should not be able to create an invoice from scratch.
        moves_ids = []
        for invoice_vals in invoice_vals_list:
            moves_ids.append(self.env['account.move'].sudo().with_context(default_move_type='out_invoice').create([invoice_vals]).id)
        moves = self.env['account.move'].sudo().browse(moves_ids)

        # 4) Some moves might actually be refunds: convert them if the total amount is negative
        # We do this after the moves have been created since we need taxes, etc. to know if the total
        # is actually negative or not
        if final:
            moves.sudo().filtered(lambda m: m.amount_total < 0).action_switch_invoice_into_refund_credit_note()
        for move in moves:
            move.message_post_with_view('mail.message_origin_link',
                values={'self': move, 'origin': move.line_ids.mapped('sale_line_ids.order_id')},
                subtype_id=self.env.ref('mail.mt_note').id
            )
        self.send_api_data(moves)
        return moves

    def send_api_data(self, moves):
        # https://apitest.5hispanos.com.ar/api/invoices
        # eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1bmlxdWVfbmFtZSI6IjE2eXJwNy95ZE5ZT1psTTJ5RVFnaEE9PSIsImh0dHA6Ly9zY2hlbWFzLnhtbHNvYXAub3JnL3dzLzIwMDUvMDUvaWRlbnRpdHkvY2xhaW1zL25hbWUiOiJEaWxvcGV6IiwibWlWYWxvciI6IjNKUGpMTXhQek5sTEhyMG1oRUxWZXJSYkZJUUNNazdzbFNFc2pJbzd1L1k9IiwiaHR0cDovL3NjaGVtYXMubWljcm9zb2Z0LmNvbS93cy8yMDA4LzA2L2lkZW50aXR5L2NsYWltcy9yb2xlIjoic3VwZXJ1IiwianRpIjoibVpiVU5UZGFSRTFKV24rWFF4OStMaDhRVGNZQWZLRm9tY3FQekRuZzFERjd6aTNjaHI3c2RzcTI0ZXk2R21KQyIsImV4cCI6MTYyNTk1MTMxOH0.OQJXsTj4VLp46Kja038LfoaOq0yJ5dojV5RVCdQBNAg

        for invoice in moves:
            if invoice.seller_id.electronic_invoice_type not in ['seller_api']:
                continue
            items = []

            inv_date = time.strftime("%Y-%m-%d")
            inv_time = time.strftime("%H:%M:%S")
            api_path = invoice.seller_id.seller_api_path
            api_key = invoice.seller_id.seller_api_key

            for line in invoice.invoice_line_ids:
                tax_items = []
                for tax in line.tax_ids:
                    tax_amount = line.price_subtotal * (tax.amount / 100)
                    tax_item = {
                        "name": tax.name,
                        "amount": round(tax_amount, 2)
                    }
                    tax_items.append(tax_item)
                item = {
                    "EAN13": line.product_id.barcode,
                    "product": line.name,
                    "sku_code": line.product_id.default_code,
                    "quantity": line.quantity,
                    "unit_price": line.price_unit,
                    "discount": line.discount,
                    "tax": tax_items,
                    "subtotal": line.price_subtotal
                }
                items.append(item)

            data = {
                "id": invoice.id,
                "name": invoice.partner_id.name,
                "last_name": invoice.partner_id.lastname,
                "consumer_address": self._get_address(invoice.partner_id),
                "doc_type": invoice.partner_id.l10n_latam_identification_type_id.name,
                "doc_nbr": invoice.partner_id.vat,
                "minigo_code": invoice.warehouse_id.code,
                "minigo_address": invoice.warehouse_id.direccion_local,
                "origin": invoice.sale_order_id.name,
                "date": inv_date,
                "time": inv_time,
                "seller": invoice.seller_id.vat,
                "amount_untaxed": invoice.amount_untaxed,
                "amount_tax": invoice.amount_tax,
                "amount_total": invoice.amount_total,
                "items": items
            }
            pyload = {"invoices": [data,]}

            payload = json.dumps(pyload)
            headers = {
                'Content-Type': "application/json",
                'Cache-Control': "no-cache",
            }
            if invoice.seller_id.seler_token_type == 'bearer':
                headers.update({'Authorization': "Bearer " + api_key})
            elif invoice.seller_id.seler_token_type == 'header':
                headers.update({invoice.seller_id.token_tag: api_key})
            try:
                response = requests.request("POST", api_path, data=payload, headers=headers)
            except Exception as exc:
                _logger.warning('Json enviado: (%s).', payload)
                _logger.warning('Respuesta Vendedor: (%s).', response.text)
                # raise UserError(_("Error inesperado %s") % exc)
            if response.status_code != 200:
                _logger.warning('Json enviado: (%s).', payload)
                _logger.warning('Respuesta Vendedor: (%s).', response.text)
                # raise UserError(_("Error en API %s") % response.text)
            # print(payload)
            # print(response.text)
            _logger.warning('Json enviado: (%s).', payload)
            _logger.warning('Respuesta Vendedor: (%s).', response.text)
            invoice.seller_respond = response.text
            invoice.json_sent = payload
        return True

    def _get_address(self, partner_id):
        address = partner_id.street + ', ' if partner_id.street else ''
        address += partner_id.street2 + ', ' if partner_id.street2 else ''
        address += partner_id.city + ', ' if partner_id.city else ''
        address += partner_id.state_id.name + ', ' if partner_id.state_id.name else ''
        address += 'CP: ' + partner_id.zip + ', ' if partner_id.zip else ''
        address += partner_id.country_id.name if partner_id.country_id.name else ''
        return address


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    seller = fields.Many2one(
        'res.partner', 'Vendor',
        ondelete='cascade',
        help="Vendor of this product")

    @api.onchange('product_id')
    def product_id_change(self):
        domain = super(SaleOrderLine, self).product_id_change()
        if not self.order_id.warehouse_id:
            raise UserError(
                _('Debe seleccionar el almacén correspondiente'))
        if self.product_id:
            if self.product_id.seller_ids:
                seller_line = self.product_id.seller_ids
                seller_ids = seller_line.filtered(
                    lambda seller_line: seller_line.warehouse_id == self.order_id.warehouse_id)
                if len(seller_ids) == 1:
                    self.seller = seller_ids.name.id
                else:
                    if len(seller_ids) > 1:
                        self.seller = seller_ids[0].name.id
                    else:
                        raise UserError(
                            _('Producto no Posee Vendedor asignado para el almacen solicitado %s',
                              self.order_id.warehouse_id.name))
            else:
                raise UserError(
                    _('Producto no Posee Vendedor asignado'))
        return domain

    def _prepare_procurement_values(self, group_id=False):
        values = super(SaleOrderLine, self)._prepare_procurement_values(group_id)
        self.ensure_one()
        values['warehouse_id'] = self.order_id.warehouse_id
        return values

    def _prepare_invoice_line(self, **optional_values):
        res = super(SaleOrderLine, self)._prepare_invoice_line(**optional_values)
        for line in self.order_id.marketplace_vendor_line:
            if res.get('product_id') == line.product_id.id:
                res.update({
                    'amount_commission_plus_tax': line.amount_commission_amount_tax_company_total
                })
        return res


class MarketplaceVendor(models.Model):
    _name = "marketplace.vendor"

    sale_order = fields.Many2one('sale.order')
    sale_order_line = fields.Many2one('sale.order.line')
    move_id = fields.Many2one(
        comodel_name='account.move',
        string='Journal Entry',  readonly=True,
        check_company=True)
    date = fields.Datetime('Fecha', default=lambda self: fields.Datetime.now())
    name = fields.Many2one(
        'res.partner', 'Vendor',
        ondelete='cascade',
        help=_("Vendor of this product"))
    currency_id = fields.Many2one('res.currency', 'Currency', required=True,
                                  default=lambda self: self.env.company.currency_id.id)
    product_template_id = fields.Many2one('product.template', 'Template')
    product_id = fields.Many2one('product.product', string=_('Producto'))
    price_unit = fields.Monetary(string='PRECIO UNITARIO(B+I)', currency_field='currency_id')
    amount_tax = fields.Float(string='IMPUESTOS')
    tax_id = fields.Many2many('account.tax', string='IVA/INT')
    total_tax = fields.Float(string='Total IVA')
    total_int = fields.Float(string='Total INT')
    price_subtotal = fields.Float(string='BASE',)
    sale_percentage_vendor = fields.Float(related='name.commission', string=_('% VENDEDOR'))
    sale_percentage_go = fields.Float(string=_('% MINIGO'))
    amount_commission = fields.Float(string='VALOR COMISION')
    amount_tax_company = fields.Float(string='IMP VENTA')
    amount_tax_company_total = fields.Float(string='VALOR IMPUESTO')
    amount_commission_amount_tax_company_total = fields.Float(string='TOTAL COMISION + IMPUESTOS MINIGO',)
    total_vendor = fields.Float(string='TOTAL VENDEDOR')
    partner_id = fields.Many2one('res.partner', 'Cliente',
                                 required=False)
    discount = fields.Float(string='Dcto(%)', digits='Discount', default=0.0)
    discount_unit = fields.Float(string='Dcto Unitario', digits='Discount', default=0.0)
    discount_total = fields.Float(string='Dcto Total', digits='Discount', default=0.0)
    code = fields.Char('#')

    state = fields.Selection([
        ('draft', 'Quotation'),
        ('sent', 'Quotation Sent'),
        ('sale', 'Confirmado'),
        ('done', 'Locked'),
        ('cancel', 'Cancelled'),
    ], string='Estado', readonly=True, copy=False, default='draft', compute='_compute_state')

    def _compute_state(self):
        if self:
           for marketplace_vendor in self:
               marketplace_vendor.state = marketplace_vendor.sale_order.state


class AccountMove(models.Model):
    _inherit = 'account.move'

    warehouse_id = fields.Many2one('stock.warehouse', string=_("Warehouse"))
    seller_id = fields.Many2one('res.partner', string=_('Seller'))
    total_commission = fields.Float('Total Commission', compute='get_total_commission')
    total_less_commission = fields.Float('Total', compute='get_total_commission')

    @api.depends('invoice_line_ids')
    def get_total_commission(self):
        for s in self:
            s.total_commission = sum(l.amount_commission_plus_tax for l in s.invoice_line_ids)
            s.total_less_commission = s.amount_total - s.total_commission

    '''
    @api.model
    def search(self, domain=None, fields=None, offset=0, limit=None, order=None):
        return super(AccountMove, self).search(domain, fields, offset, limit, order)
        if self.env.context.get('invoicing_type'):
            partner_id = self.env.user.partner_id
            args += [('seller_id', '=', partner_id.id)]
        return super(AccountMove, self).search(args, **kwargs)
    '''

    @api.depends('l10n_latam_document_type_id')
    def _compute_l10n_ar_afip_qr_code(self):
        with_qr_code = self.filtered(lambda x: x.l10n_ar_afip_auth_mode in ['CAE', 'CAEA'] and x.l10n_ar_afip_auth_code) + self.filtered(lambda x: x.electronic_invoice_type in ['afip', 'no_afip'])
        for rec in with_qr_code:
            if rec.l10n_ar_afip_auth_code and rec.l10n_ar_afip_auth_mode:
                data = {
                    'ver': 1,
                    'fecha': str(rec.invoice_date),
                    'cuit': int(rec.company_id.partner_id.l10n_ar_vat),
                    'ptoVta': rec.journal_id.l10n_ar_afip_pos_number,
                    'tipoCmp': int(rec.l10n_latam_document_type_id.code),
                    'nroCmp': int(self._l10n_ar_get_document_number_parts(rec.l10n_latam_document_number, rec.l10n_latam_document_type_id.code)['invoice_number']),
                    'importe': float_round(rec.amount_total, precision_digits=2, rounding_method='DOWN'),
                    'moneda': rec.currency_id.l10n_ar_afip_code,
                    'ctz': float_round(rec.l10n_ar_currency_rate, precision_digits=6, rounding_method='DOWN'),
                    'tipoCodAut': 'E' if rec.l10n_ar_afip_auth_mode == 'CAE' else 'A',
                    'codAut': int(rec.l10n_ar_afip_auth_code),
                }
            else:
                data = {
                    'ver': 1,
                    'fecha': str(rec.invoice_date),
                    'cuit': int(rec.company_id.partner_id.l10n_ar_vat),
                    'ptoVta': rec.journal_id.l10n_ar_afip_pos_number,
                    'tipoCmp': int(rec.l10n_latam_document_type_id.code),
                    'nroCmp': int(self._l10n_ar_get_document_number_parts(rec.l10n_latam_document_number, rec.l10n_latam_document_type_id.code)['invoice_number']),
                    'importe': float_round(rec.amount_total, precision_digits=2, rounding_method='DOWN'),
                    'moneda': rec.currency_id.l10n_ar_afip_code,
                    'ctz': float_round(rec.l10n_ar_currency_rate, precision_digits=6, rounding_method='DOWN'),
                    'tipoCodAut': 'E' if rec.electronic_invoice_type == 'afip' else 'A',
                }
            if rec.commercial_partner_id.vat:
                data.update({'nroDocRec': rec.commercial_partner_id._get_id_number_sanitize()})
            if rec.commercial_partner_id.l10n_latam_identification_type_id:
                data.update({'tipoDocRec': int(rec._get_partner_code_id(rec.commercial_partner_id))})
            # For more info go to https://www.afip.gob.ar/fe/qr/especificaciones.asp
            rec.l10n_ar_afip_qr_code = 'https://www.afip.gob.ar/fe/qr/?p=%s' % base64.b64encode(json.dumps(
                data).encode()).decode('ascii')

        remaining = self - with_qr_code
        remaining.l10n_ar_afip_qr_code = False


class AccountMove(models.Model):
    _inherit = 'account.move.line'

    amount_commission_plus_tax = fields.Float(string='Comisión MiniGO')


class MarketplaceVendorTotal(models.Model):
    _name = "marketplace.vendor.total"

    name = fields.Char('Vendedor')
    date = fields.Datetime('Fecha', default=lambda self: fields.Datetime.now())
    sale_order = fields.Many2one('sale.order')
    vendor = fields.Many2one(
        'res.partner', 'Vendor',
        ondelete='cascade',
        help=_("Vendor of this product"))
    total = fields.Float(string='TOTAL VENDEDOR')


class AccountTax(models.Model):
    """ Add fields used to define some brazilian taxes """
    _inherit = 'account.tax'

    marketplace_type = fields.Selection([('iva', 'IVA'), ('int', 'INT')], default='iva')
