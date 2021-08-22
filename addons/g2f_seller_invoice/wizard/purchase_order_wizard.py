from odoo import models, fields, api, _
import datetime
import time
from zeep import Client, xsd
from zeep.exceptions import Fault
from lxml import etree as ET
import base64
from odoo.modules.module import get_module_resource
from odoo.exceptions import except_orm, Warning, RedirectWarning

import logging
_logger = logging.getLogger(__name__)


class PurchaseOrderWizard(models.TransientModel):
    _name = 'purchase.order.wizard'
    _description = "Purchase Order Wizard"

    data = fields.Text('Data')

    def send_po(self):
        ids = self._context.get('active_ids')
        po_ids = self.env['purchase.order'].search([('id', 'in', ids)])
        send_date = time.strftime("%Y%m%d")
        send_time = time.strftime("%H%M")
        _logger.info("### Lista ### %r", po_ids.read())
        for po in po_ids:
            info = 'INFO'
            info += '9500000598565'.zfill(13)  # EAN del emisor
            info += po.partner_id.vat.replace('-', '').zfill(13)  # '9930566108352'.zfill(13)  # EAN del Proveedor
            info += 'ORDERS'

            head = 'HEAD'
            head += '9500000598565'.zfill(13)  # EAN del emisor
            head += po.partner_id.vat.replace('-', '').zfill(13)  # EAN del Proveedor
            head += '9500000598565'.zfill(13)  # EAN de la boca de entrega
            head += ''.ljust(4)
            head += po.name.ljust(10)
            head += ''.ljust(10)  # Código del proveedor
            head += po.partner_id.name.ljust(35)  # Descripción del Proveedor
            head += self._get_address(po.partner_id)[:35].ljust(35)
            head += ''.ljust(120)
            head += po.date_order.strftime('%Y%m%d') if po.date_order else ''
            head += "  " + po.date_planned.strftime('%Y%m%d') if po.date_planned else ''.ljust(12)
            head += "  " + po.date_approve.strftime('%Y%m%d') if po.date_approve else ''.ljust(12)
            head += ''.ljust(35)  # Forma de Pago / Observaciones
            head += ''.ljust(5)
            head += str(po.amount_total).zfill(15)
            head += send_date[2:]
            head += send_time
            head += ''.ljust(145)
            head += po.name.ljust(20)

            detail = 'LINE'
            detail += str(len(po.order_line)).zfill(6)
            for line in po.order_line:
                barcode = line.product_id.barcode or ''
                default_code = line.product_id.default_code or ''
                detail += barcode.ljust(14)
                detail += line.name.ljust(35)
                detail += line.name.ljust(35)
                detail += default_code.zfill(14)
                detail += ''.ljust(7)
                detail += ''.zfill(7)  # Cantidad pedida en cajas (Package)
                detail += ''.zfill(11)  # Cantidad pedida en unidades
                detail += ''.zfill(5)  # Cantidad de unidades por package
                detail += ''.ljust(17)
                detail += str(line.price_unit).zfill(15)
                detail += ''.ljust(15)
                detail += str(line.price_subtotal).zfill(15)
                detail += ''.ljust(80)

            data = info + '\n' + head + '\n' + detail
            print(data)

            # file_content = base64.b64encode(bytes(data, 'utf-8'))
            file_content = base64.b64encode(data.encode('utf-8'))
            #file_content = b'dGVzdDQ='
            function = 'ORDERS'
            file_name = po.name + '.txt'
            wsdl = get_module_resource('g2f_seller_invoice', 'wizard/', 'PlanexwareWsWsdl')
            client = Client(wsdl)
            client.set_ns_prefix(None, "https://ws.planexware.net")
            settings = {
                'Ocp-Apim-Subscription-Key': '1381fbeede8243c6b87322169b623d8e',
                'Company': 'GO2FUTURE',
            }
            client.settings.extra_http_headers = settings
            client.settings.raw_response = True

            header = xsd.ComplexType(
                xsd.Sequence([
                    xsd.Element("Function", xsd.String()),
                    xsd.Element("FileName", xsd.String()),
                ])
            )

            header_value = header(Function=function, FileName=file_name)
            print(header_value)

            # Para imprimir el xml que  se envia
            node = client.create_message(client.service, 'Upload', FileContent=file_content, _soapheaders=[header_value])
            tree = ET.ElementTree(node)
            # tree.write('test.xml', pretty_print=True)
            print(ET.tostring(tree, pretty_print=True, encoding=str))

            try:
                response = client.service.Upload(FileContent=data.encode('utf-8'), _soapheaders=[header_value])
                print(response.status_code)
                print(response.ok)
                print(response.text)
                _logger.info("### Status Code ### %r", response.status_code)
                _logger.info("### XML Response ### %r", response.text)
                po.write({'pw_status_code': response.status_code, 'pw_xml_response': response.text})
            except Fault as error:
                print(error)
                _logger.info("### Send Error ### %r", error)

    def _get_address(self, partner_id):
        address = partner_id.street + ', ' if partner_id.street else ''
        address += partner_id.street2 + ', ' if partner_id.street2 else ''
        address += partner_id.city + ', ' if partner_id.city else ''
        address += partner_id.state_id.name + ', ' if partner_id.state_id.name else ''
        address += 'CP: ' + partner_id.zip + ', ' if partner_id.zip else ''
        address += partner_id.country_id.name if partner_id.country_id.name else ''
        return address
