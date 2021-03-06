# pylint: disable=broad-except

import logging
import requests
from json import dumps, loads
from urllib.parse import urljoin

from odoo import http, _
from odoo.exceptions import ValidationError, UserError


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
_logger = logging.getLogger(__name__)


class AccessControl(http.Controller):
    """Access Control Controller."""

    def _validate_user(self, login=''):
        """validate user is exist y return instance."""

        user = http.request.env['res.users']
        return user.sudo().search([('login', '=', login)])

    def get_store_by_id(self, store_id):
        """Get Store from id passed."""

        store = http.request.env['stock.warehouse'].sudo().search(
                [('id', '=', store_id)]
                )
        return store

    def _open_door_access_control(self, store_id, door_id, login,
                                  role='customer'):
        """Send to AccessControl open Door."""

        base_url = self.get_store_by_id(store_id).access_control_url
        command = 'OpenDoor'
        params = {"storeCode": int(store_id),
                  "doorId": int(door_id),
                  "userId": login,
                  "token": "G02Future$2021",
                  "role": role}
        url = urljoin(base_url, command)

        try:
            # timeout=0.001
            msg = """*** Se pidio a control de acceso entrar. ***
                    El endpoint es:{} y los parametros son:{}
                  """.format(url, params)
            _logger.info(msg)

            response = requests.post(url, json=params)
            _logger.info('Control de Acceso responde:{}'.format(response.text))
        except Exception as Error:
            return dumps({"status": "400", "message": str(Error)})

        try:
            resp = loads(response.text)
            resp.update({"role": role})
        except Exception as ErrorResponse:
            resp = response
            _logger.error({"Ocurrio un error  ": "desconocido", 
                "message": str(ErrorResponse)})

        return dumps(resp)

    def _confirm_payment_to_access_control(self, store_id, door_id, login,
                                           was_confirmed):
        """Send to AccessControl confirm payment."""

        base_url = self.get_store_by_id(store_id).access_control_url
        command = 'ConfirmPayment'
        params = {"storeCode": int(store_id),
                  "doorId": int(door_id),
                  "userId": login,
                  "wasConfirmed": was_confirmed,
                  "token": "G02Future$2021"}
        url = urljoin(base_url, command)

        msg = """*** Enviar a control de acceso para que abra la puerta. ***
                 El endpoint es:{} y los parametros son:{}
              """.format(url, params)
        _logger.info(msg)

        try:
            response = requests.post(url, json=params)
            _logger.info('Control de acceso responde')
            _logger.info(response)
            _logger.info(response.text)
        except Exception as Error:
            _logger.error(Error)
            return dumps({"status": "400", "message": str(Error)})

        return response.text

    @http.route(['/users/EnterStore'], type='json', auth='public',
                methods=['POST'],
                website=True, csrf=False)
    def enter_store(self, **kw):
        """Endpoint when user enter Store."""

        method = http.request.httprequest.method
        kw = http.request.jsonrequest

        login = kw.get('login')
        door_id = kw.get('door_id')
        store_id = kw.get('store_id')
        type_ = kw.get('type')
        role = 'customer'

        if method == 'POST':
            user = self._validate_user(login)
            if user:
                _logger.info(f"Id usuario:{user.id}, {user.login}")

                if user.is_staff():
                    role = 'staff'

                store = self.get_store_by_id(store_id)
                if not store:
                    msg = _('Store dont exist.')
                    response = {"status": "400", "message": msg}
                    _logger.info(response)
                    return dumps(response)

                if type_.lower() not in ['in'] and not user.is_staff():
                    msg = _('Door is not an entrance.')
                    response = {"status": "403", "message": msg}
                    _logger.info(response)
                    return dumps(response)

                # Prepare url endpoint and send to Access control server
                res = self._open_door_access_control(store_id, door_id, login,
                                                     role)
                return res

            msg = _('User dont exists!')
            response = {'status': '400', 'messsage': msg}
            _logger.info(response)
            return dumps(response)
        return False

    @http.route(['/test'], type='http', auth='user', methods=['GET'],
                website=True, csrf=False)
    def test(self, **kw):
        print(kw)
        print(http.request.session.get('login'))

    @http.route(['/get_message_access_control'], type='json', auth='public',
                methods=['POST'],
                website=True, csrf=False)
    def message_from_access_control(self, **kw):
        """get message from access control."""

        method = http.request.httprequest.method
        kw = http.request.jsonrequest
        transaction = http.request.env['apirest.transaction']

        login = kw.get('userId')
        store_id = kw.get('storeCode')
        door_id = kw.get('doorId')
        code = kw.get('code')
        message = kw.get('message')
        msg_for_app_mobile = ''
        role = 'Customer'
        exitdoor = 3

        sale_order = http.request.env['sale.order'].sudo()
        user = http.request.env['res.partner'].sudo().validate_user(login)

        _logger.info("Recibi de get_message_access_control el codigo: %s", code)

        if method == 'POST' and user:
            if user.is_staff():
                msg_for_app_mobile = 'is staff'
                message = _('is staff')

            if code == 4 and not user.is_staff():
                # Jenny pide que cuando sea el codigo 4 por ahora
                # No se le envie nada a la App mobile
                msg_for_app_mobile = "" 
                message = ""

            if code == 7 and not user.is_staff():
                # Crear la sale order
                sale_order.create_sale_order(user.partner_id.id, store_id)
                msg_for_app_mobile = _('sales order was created successfully')
                message = _('OK')

            elif code == 9:
                _logger.info('recibi el codigo 9 de control de acceso')
                order = sale_order._search_sale_order_by_partner(user.partner_id.id)
                # codigo 9 significa que control de acceso espera que se
                # confirme el pago

                # Valido que tenga algo pendiente por pagar o se va sin nada
                if order.is_pending_order_to_pay():
                    _logger.info('Tiene orden pendiente por pagar')

                    # Tiene productos en el carrito se confirma la sale order
                    order.confirm_sale_order()

                    # Ahora validar que el pago se efectuo
                    if order.sudo().is_payment_approved():
                        code = 100
                        msg_for_app_mobile = _('successful payment')
                        message = _("Successful payment")
                        # enviar a control de acceso que todo esta bien
                        self._confirm_payment_to_access_control(store_id, door_id, login, True)
                        self._open_door_access_control(store_id, exitdoor, login, "staff")
                    else:
                        code = 0
                        msg_for_app_mobile = _("Payment declined")
                        message = _('Payment declined')
                        # enviar a control de acceso que algo no esta bien
                        self._confirm_payment_to_access_control(store_id, door_id, login, False)
                else:
                    code = 111
                    msg_for_app_mobile = _(
                            'Customer does not have products pending payment')

                    order.cancel_sale_order()
                    _logger.info('Carrito esta en 0')

                    msg_for_app_mobile = _('successful payment')
                    message = _('Successful payment')
                    # enviar a control de acceso que todo esta bien
                    self._confirm_payment_to_access_control(store_id, door_id, login, True)
                    self._open_door_access_control(store_id, exitdoor, login, "staff")
            elif code == 10:
                # Cuando ya salio de la tienda
                pass

            # Nueva forma de el cliente dejar los productos
            # Este codigo lo recibo es desde la app mobile (Alan)
            elif code == 11:
                # El cliente decidio el mismo dejar los prductos en la gondola
                # Pide a contrl de acceso que le abra la puerta 1 de salida
                # Para dejar el los productos
                # Prepare url endpoint and send to Access control server

                #door_id = 9 # Puerta de salida hacia la tienda
                self._open_door_access_control(store_id, door_id, login, "staff")
                msg_for_app_mobile = _('Se pidio a control de acceso abrir la puerta de salida a la tienda')
                message = _('Please Open door {}'.format(door_id))

                # Esto esta deprecado ya que ya vision no me avisa cuando el cliente
                # Decide dejar los productos.
                '''elif code == 11:
                    # El cliente decidio dejar los productos y retirtarse
                    # Validar tambien que la sale order este en 0
                    order = sale_order._search_sale_order_by_partner(
                            user.partner_id.id)
                    if order.is_pending_order_to_pay():
                        msg_for_app_mobile = _(
                                """
                                Sorry, you cannot leave the store,
                                products were detected in the cart"""
                                )
                    else:
                        msg_for_app_mobile = _('Customer leaves the products and leaves the store')
                        message = _('Please Open door 1 and 2')

                        # Aqui yo deberia cancelar la sale order
                        order.cancel_sale_order()
                        '''
                # ---------  Fin de codigo 11 -----------------------------------
            else:
                # Si no es ninguno de los codigos anteriores
                _logger.info("No es niguno de los codigos que yo espero")
                _logger.info(kw)

            # tomar el mensaje y guardarlo en el model transaction para que
            # la app le llegue el mensaje y tome una decision.
            _logger.info(' Se guarda en transaction-> Login:{}- code:{} - msg:{}'.format(
                login, code, msg_for_app_mobile))
            transaction.sudo().create_transaction(login, store_id, door_id,
                                                  code, msg_for_app_mobile,
                                                  'access_control')
            response = {'status': '200', 'message': message}
            _logger.info("Se le devuelve a control de acceso{0}".format(response))
            return response

        response = {'status': '400', 'message': 'NOT FOUND'}
        return dumps(response)

    @http.route(['/users/send_message_access_control'], type='json', auth='public',
                methods=['POST'],
                website=True, csrf=False)
    def send_message_to_access_control(self, **kw):
        """recive from app mobile and send message to access control."""

        method = http.request.httprequest.method
        kw = http.request.jsonrequest

        if method == 'POST':
            # Get params from app mobile
            login = kw.get('login')
            store_id = kw.get('store_id') or 1
            door_id = kw.get('door_id') or 0
            was_confirmed = kw.get('was_confirmed')
            # token = 'aqui un token'

            # Prepare url endpoint and send to Access control server
            base_url = self.get_store_by_id(store_id).access_control_url
            endpoint = 'ConfirmAtHall'
            params = {"storeCode": int(store_id), "doorId": int(door_id),
                      "userId": login, "WasConfirmed": was_confirmed,
                      "token": "G02Future$2021"
                      }
            send_access_store_response = requests.post(urljoin(base_url,
                                                       endpoint), json=params)

            _logger.info('login:{}, store_id:{}, door_id:{}, was_confirmed:{}'.format(login, store_id, door_id, was_confirmed))
            _logger.info('Url server: {}'.format(urljoin(base_url, endpoint)))
            _logger.info('Control de acceso devuelve: {}'.format(send_access_store_response))

            return send_access_store_response
