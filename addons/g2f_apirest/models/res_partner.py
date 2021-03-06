# pylint: disable=eval-used
# pylint: disable=eval-referenced
# pylint: disable=consider-add-field-help
# pylint: disable=broad-except
# -

import base64
from datetime import datetime
import logging
from odoo import models, fields
from odoo.modules.module import get_module_resource


logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _default_image(self):
        image_path = get_module_resource('g2f_apirest', 'static/src/img',
                                         'default_image.png')
        return base64.b64encode(open(image_path, 'rb').read())

    GENDER = [
        ('M', 'Male'),
        ('F', 'Female'),
        ('O', 'Other')]

    lastname = fields.Char(string='Apellidos')
    birthday = fields.Date(string='Cumpleaños')
    gender = fields.Selection(GENDER, string='Sexo')
    document_obverse = fields.Image(default=_default_image)
    document_reverse = fields.Image(default=_default_image)
    user_avatar = fields.Image()
    terms_conditions_agreement = fields.Boolean(default=False)
    email_recipe_receive = fields.Boolean(default=False)

    def name_get(self):
        result = []
        for record in self:
            name = record.name
            if record.lastname:
                name += f" {record.lastname}"

            result.append((record.id, name))
        return result

    def age(self):
        age = 0
        for record in self:
            if record.birthday:
                today = datetime.now().date()
                age_rest = (today - record.birthday)
                age = round(age_rest.days/365)
        return age

    def validate_user(self, login=''):
        """ Validate if email exist.

        Parameters:
        email: str"""

        user = self.user_ids.search([('email', '=', login)])
        return user or None

    def document_exist(self, identification_type, document):
        """validate if exist document and identification_type.

        Parameters:
        identification_type: str
        document: str"""

        document = self.search([
            ('l10n_latam_identification_type_id.name', 'ilike', identification_type),
            ('vat', '=', document),
            ('active', '=', True)
        ])
        return document or None

    def search_country_state_by_name(self, country_name='', state_name=''):
        """Search ID from Country and State.

        Parameter:
            country_name: str
            state_name: str"""

        country_id, state_id = None, None

        if country_name and state_name:
            domain_country = [('name', 'ilike', country_name)]
            country = self.env['res.country'].search(domain_country)

            domain_state = [('name', 'ilike', state_name), ('country_id', '=', country.id)]
            state = self.env['res.country.state'].search(domain_state, limit=1)

            country_id = country.id if country else None
            state_id = state.id if state else None

        return country_id, state_id

    def search_identification_type(self, identification_type):
        """Search identification_type and return objects instance.

        Parameters:
        identification_type: str
        """

        identification_type = self.env['l10n_latam.identification.type'].search([
            ('name', 'ilike', identification_type),
            ('active', '=', True)
        ])
        return identification_type or None

    def list_identification_type(self):
        """ Return identification_type list objects instance."""

        identification_type_list = self.env['l10n_latam.identification.type'].search([
            ('active', '=', True)
        ])
        return [identification.name for identification in identification_type_list]

    def list_l10n_ar_afip_responsability_type(self):
        """Return responsibility afip type:
            1 IVA Responsable Inscripto
            5 Consumidor Final
            6 Responsable Monotributo."""

        domain = [('id', 'in', [1, 5, 6])]
        rt = self.env['l10n_ar.afip.responsibility.type'].search(domain)

        return [{'id': responsibility.id, 'name': responsibility.name} for 
                responsibility in rt]

    def search_country_info(self, country=''):
        """Search countries or country from app mobile.

        Parameters:
            country: str"""

        domain = [('name', 'ilike', country)] if country else []
        countries = []
        country = self.env['res.country'].search(domain)
        for country in country:
            countries.append({country.name: [{'state': state.name, 'code': state.code} for state in country.state_ids],
                              'code': country.code,
                              'currency': country.currency_id.name,
                              'phone_code': country.phone_code,
                              })
        return countries

    def get_payment_card(self):
        """Get Payment Card data from unser passed in instance self from
        controllers."""

        lista = [(t.id, t.name, t.card_number, t.security_code, t.expiration_month,
                t.expiration_year, t.card_type, t.card_identification.name, t.state) 
                for t in self.payment_cards_ids
                ]
        return lista

    def create_payment_card(self, vals):
        """Create new card credit to res.partner."""

        payment_cards = self.env['payment.cards']
        payment_cards.create(vals)
        payment_cards._cr.commit()

    def update_payment_card(self, vals):
        """Update card credit to res.partner."""

        if vals.get('state') == 'active':
            for tdc in self.payment_cards_ids:
                tdc.state = 'disabled'
            self.payment_cards_ids._cr.commit()

        payment_card = self.payment_cards_ids.search([('id', '=', vals.get('id'))])
        payment_card.write(vals)
        payment_card._cr.commit()

    def delete_payment_card(self, vals):
        """Delete card credit to res.partner."""

        payment_card = self.payment_cards_ids.search([('id', '=', vals.get('id'))])
        payment_card.unlink()
        payment_card._cr.commit()

    def payment_cards_type_list(self):
        """Get payment_cards_type_list and return a generators list."""

        # return ((f.name, f.payment_method_id) for f in self.env['payment.cards.types'].search([]))
        return ((f.name, f.id) for f in self.env['payment.cards.types'].search([]))

    def get_data_user(self):
        """Parse data for user."""

        child_ids = [
                ({
                    'id': f.id, 'email': f.email, 'name': f.name, 'phone': f.phone,
                    'mobile': f.mobile, 'street': f.street,
                    'country': f.country_id.name, 'state': f.state_id.name,
                    'city': f.city, 'zip': f.zip, 'comment': f.comment
                    }) for f in self.child_ids
                ]

        res_partner = {"name": self.name,
                       "lastname": self.lastname,
                       "login": self.email,
                       "birthday": self.birthday.strftime('%Y-%m-%d') if self.birthday else None,
                       "gender": self.gender,
                       "identification_type": self.l10n_latam_identification_type_id.name,
                       "afip_responsibility_type_id": self.l10n_ar_afip_responsibility_type_id.name,
                       "vat": self.vat,
                       "address": self.street,
                       "country": self.country_id.name,
                       "country_state": self.state_id.name,
                       "state_city": self.city,
                       "business_name": '',
                       "phone": self.phone or '',
                       "password": self.user_id.password,
                       "avatar": self.user_avatar.decode('ascii') if self.user_avatar else '',
                       "child_ids": child_ids}

        return res_partner if res_partner else ''
