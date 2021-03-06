# pylint: disable=broad-except

from datetime import datetime
import logging
import requests
from json import dumps
from odoo import http, _
# from odoo.exceptions import ValidationError, UserError


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
_logger = logging.getLogger(__name__)


class SaleOrderCart(http.Controller):
    @http.route(['/user_cart'], type='json', auth='public',
                methods=['GET'], website=True, csrf=False)
    def get_user_cart_from_vision(self, **kw):
        """get the list of items that a user has in the cart for Vision."""

        method = http.request.httprequest.method

        user_id = kw.get('user_id')

        sale_order = http.request.env['sale.order']
        products = {}

        if method == 'GET':
            # Obtener lista de productos de orden de venta abierta
            response = sale_order.sudo()._get_sale_order_from_controller(user_id)

            # Parsear para vision: {'barcode': cantidad, 'barcode': cantidad}
            for producto in response:
                if isinstance(producto, dict):
                    barcode = producto.get('barcode')
                    qty = producto.get('product_uom_qty')
                    products.update({barcode: int(qty)})
            return products

    @http.route(['/cart_update'], type='json', auth='public',
            methods=['GET', 'POST'], website=True, csrf=False)
    def user_cart_from_vision(self, **kw):
        """Update or Get sale order to for  vision system."""

        method = http.request.httprequest.method
        kw = http.request.jsonrequest

        user_id = kw.get('user')
        barcode = kw.get('product')
        quantity = kw.get('quantity')
        action = kw.get('action')
        sensor = kw.get('sensor')

        sale_order = http.request.env['sale.order']

        if method == 'GET':
            # Obtener lista de productos de orden de venta abierta
            response = sale_order.sudo()._get_sale_order_from_controller(user_id)
            return response

        if method == 'POST':
            #  Agregar un prodcuto a una orden de venta
            response = sale_order.sudo()._add_products_from_controller(user_id, barcode, quantity, sensor, action)
            if response:
                return http.Response('CREATED', status=201)
            return http.Response('NOT FOUND', status=404)

    @http.route(['/sale_order_cart'], type='http', auth='public',
                methods=['GET'], website=True, csrf=False)
    def sale_order_cart(self, **kw):
        """Get sale order open y returm to app mobile."""

        print(kw)
        method = http.request.httprequest.method
        login = kw.get('login')

        sale_order = http.request.env['sale.order']

        if method == 'GET':
            # Obtener lista de productos de orden de venta abierta
            response = sale_order.sudo()._get_sale_order_from_controller(
                login)
            return dumps(response)

        return http.Response('NOT FOUND', status=404)

    @http.route(['/sale_order_list/', '/sale_order_list/page/<int:page>',
                 '/sale_order_list/page'],
                type='http', auth='public', methods=['GET'], website=True,
                csrf=False)
    def sale_order_list(self, page=0, **kw):
        '''Get sale order list closed by login.'''

        page = page or 1
        method = http.request.httprequest.method
        user_id = kw.get('login')
        order_for_page = kw.get('order_for_page') or 6

        sale_order = http.request.env['sale.order']

        if method == 'GET':
            response = sale_order.sudo().get_sale_order_list(user_id,
                                                             page,
                                                             int(order_for_page)
                                                             )
            _logger.info(response)
            return dumps(response)

        return http.Response('NOT FOUND', status=404)

    @http.route(['/sale_order_detail/'], type='http', auth='public',
                methods=['GET'], website=True, csrf=False)
    def sale_order_detail(self, **kw):
        '''Get sale order list by login.'''

        print(kw)
        method = http.request.httprequest.method
        order = kw.get('sale_order')

        domain = [('name', '=', order)]
        sale_order = http.request.env['sale.order'].sudo().search(domain)

        if method == 'GET' and sale_order:
            response = sale_order.sudo()._list_sale_order_cart(sale_order)
            return dumps(response)

        return http.Response('NOT FOUND', status=404)

    @http.route(['/products_in_carts'], type='json', auth='public', methods=['POST'], website=True, csrf=False)
    def products_in_carts(self, **kw):
        """Update or Get sale order to for  vision system."""

        method = http.request.httprequest.method
        kw = http.request.jsonrequest

        store_code = kw.get('store_code')
        store_id = http.request.env['stock.warehouse'].sudo().search([("code", "=", store_code)])
        if not store_id:
            return http.Response('NOT FOUND STORE', status=404)
        response = {}
        sale_order_line = http.request.env['sale.order']
        if method == 'POST':
            #  Agregar un prodcuto a una orden de venta
            data = sale_order_line.sudo()._products_in_carts(store_id.id)
            if data:
                response['store_code'] = store_code,
                response['status'] = 200,
                response['success'] = True,
                response['data'] = data
                return response
            return http.Response('NOT FOUND', status=404)
