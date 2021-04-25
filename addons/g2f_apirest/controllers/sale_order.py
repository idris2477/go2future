# pylint: disable=broad-except

from datetime import datetime
import requests
from json import dumps
from odoo import http, _
# from odoo.exceptions import ValidationError, UserError


class SaleOrderCart(http.Controller):
    @http.route(['/user_cart'], type='json', auth='public',
            methods=['GET', 'PUT', 'POST', 'DELETE'], website=True, csrf=False)
    def sale_order_cart(self, **kw):
        method = http.request.httprequest.method
        kw = http.request.jsonrequest

        user_id = kw.get('user')
        product_id = kw.get('product')
        action = kw.get('action')

        sale_order = http.request.env['sale.order']

        if method == 'GET':
            # Obtener lista de productos de orden de venta abierta

            response = sale_order.sudo()._get_sale_order_from_controller(
                    user_id)
            return dumps(response)

        if method == 'POST':
            #  Agregar un prodcuto a una orden de venta

            response = sale_order.sudo()._add_products_from_controller(
                    user_id, product_id, action)
            if response:
                return http.Response('CREATED', status=201)
            return http.Response('NOT FOUND', status=404)
