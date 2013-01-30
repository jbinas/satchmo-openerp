from django.conf import settings
from oesync.fields import *


# EDITING THE FIELD MAPPING
#
# The mapping of Satchmo objects to OpenErp objects is specified using the
# following structure:
#
# 'SatchmoModel': {
#    'openerp.model': {
#        'fieldname1': FieldType1('parameter1'),
#        'fieldname2': FieldType2('parameter2'),
#        ...
#    },
#    ...
# }
#
# The mapping named 'SatchmoModel' is called whenever an object of the
# Satchmo model 'SatchmoModel' is created, updated or deleted. This
# means, OESync creates, updates, or deletes an object of the OpenErp
# model 'openerp.model'. If the object is created or updated, its data
# is generated as specified by the 'FieldType' objects.
#
# One Satchmo model can map to multiple OpenErp models (multiple OpenErp
# models 'openerp.model' can be specified in one mapping and they will be
# updated one by one. If update order matters, they can be nested, i.e.
# in a mapping to one OpenErp model you can specify a mapping to another
# OpenErp model (see the 'Product' mapping below for illustration). This
# child model is mapped when updating of the parent model is done.
#
#
# FIELD TYPES
#
# Static Field
# 'field': StaticField('value')
# Use this to always sets the field 'field' of the OpenErp object to 'value'
#
# Standard Field
# 'field': StdField('attribute_name', 'default_value')
# This uses the attribute or method named 'attribute_name' of the
# Satchmo object to generate the content of the field 'field'. For
# example, specifying 'email': StdField('contact.email') in the
# 'res.partner' mapping of 'AddressBook' sets the 'email' field of the
# 'res.partner' object to the value returned by
# AdrBookObj.contact.email, where AdrBookObj is the AddressBook object
# that is being synchronized.
#
# ID Field
# 'field': IdField('attribute_name', 'openerp_model')
# This is similar to StdField, but sets the field value to the id of the
# OpenErp object of 'openerp_model' corresponding to the Satchmo id
# returned by the 'attribute_name' attribute of the Satchmo object. If
# no OpenErp model is specified the model that is currently being mapped
# is assumed. See sample mapping below for illustration.
#
# Foreign ID Field
# 'field': ForeignIdField('attribute_name', 'satchmo_model',
# 'openerp_model')
# Similar to IdField, however, adds the possibility of specifying a
# Satchmo model different from the one that is currently being mappen.
# See sample mapping below for illustration.
#
# Bool Field
# 'field': BoolField('attribute_name', 'check_value')
# This returns True if the value returned by the 'attribute_name'
# attribute of the Satchmo object is equal to 'check_value'. See the
# 'customer' field of the 'res.partner' model, for example. This is set
# to True if the 'contact.role_id' attribute of the AddressBook object
# returns 'Customer'.
#
# Selection Field
# 'field': SelectionField('attribute_name', 'dict')
# Translate the value according to values specified in the 'dict'
# dictionary. The special key '_default' allows setting a value if no
# key corresponding to the value returned by the 'attribute_name'
# attribute of the Satchmo object is specified.
#
#
#
# If things are not clear immediately, have a look at the sample mapping
# below -- it's rather simple.
#
#
# NOTE:
# OESync automatically runs a number of actions whenever an order is
# completed, to automatically validate the order and create an invoice
# and payments. This can not be changed here. In order to disable this
# behavior, simply remove the registration of the on_order_success
# signal in __init__.py


#set a few variables first
company_id = settings.OPENERP_SETTINGS['COMPANY_ID']
currency_id = settings.OPENERP_SETTINGS['CURRENCY_ID']


mapping = {

    #'Contact': NotImplemented
    # Currently not implemented because of the new unified partner model in OE 7.
    # This should be fixed as soon as OE modules exist that allow multiple
    # addresses (shipping/invoice/contact) per partner.

    'AddressBook': {
        'res.partner': {
            #'category_id': StaticField([1]), #Add 'Partner' tag
            #you might want to add a category corresponding to
            #your online shop: [1] --> [1, additional_categ_id]
            'city': StdField('city'),
            'comment': StdField('contact.notes'),
            'company_id': StaticField(company_id), #OpenERP ID corresponding to your eShop
            'country_id': ForeignIdField('country_id', 'Country', 'res.country'),
            'customer': BoolField('contact.role_id', 'Customer'),
            'supplier': BoolField('contact.role_id', 'Supplier'),
            'employee': BoolField('contact.role_id', 'Employee'),
            'email': StdField('contact.email'),
            'parent_id': ForeignIdField('contact.organization_id', 'Organization'),
            'phone': StdField('contact.primary_phone.phone', default=False),
            'name': StdField('addressee'),
            #'name': StdField('contact.full_name'),
            #'opt_out': StaticField(True), #opt out partners from auto emails
            #'state_id': NotImplemented, #ids in OE vs. strings in Satchmo...
            'street': StdField('street1'),
            'street2': StdField('street2'),
            #'title': NotImplemented,
            'type': StdField('description'), #TODO: create AddressType model
            'zip': StdField('postal_code'),
        },
    },

    'Organization': {
        'res.partner': {
            'name': StdField('name'),
            'customer': BoolField('role', 'Customer'),
            'supplier': BoolField('role', 'Supplier'),
            'is_company': StaticField(True),
            'comment': StdField('notes'),
        },
    },

    'Country': {
        'res.country': {
            'code': StdField('iso2_code'),
            'name': StdField('printable_name'),
        },
    },

    'Category': {
        '_ACCESS_INLINE': True,
        '_ADMIN_CLASS': 'product.admin.CategoryOptions',

        'product.category': {
            'name': StdField('name'),
            'parent_id': IdField('parent_id'),
            'type': StaticField('normal'),
            #'description': StdField('description'), #TODO: add those fields
            #'meta': StdField('meta'),
        },
    },

    'Product': {
        '_ACCESS_INLINE': True,
        '_ADMIN_CLASS': 'product.admin.ProductOptions',

        'product.template': {
            'categ_id': ForeignIdField('main_category.id', 'Category',
                                       'product.category'),
            'categ_ids': ManyForeignIdField('category', 'Category',
                                            'product.category'),
            'cost_method': StaticField('standard'),
            #'description': StdField('description'),
            'description_sale': StdField('description'),
            #'description_purchase': StdField('description'),
            'sale_ok': StdField('active'),
            'list_price': StdField('unit_price.to_eng_string()'),
            'mes_type': StaticField('fixed'), #You might want to change this
            'name': StdField('name'),
            'supply_method': StaticField('buy'),
            'type': StaticField('product'),
            'uom_id': StaticField(1), #Set unit of measure/sale to 'Unit'
            #'uom_po_id': StaticField(1),
            'uos_coeff': StaticField(1.),
            'weight': StdField('weight'),

            'product.product': {
                '_AUTO_DELETE': True, #only delete parent object

                'product_tmpl_id': IdField('id', 'product.template'),
                'name_template': StdField('name'),
                'valuation': StaticField('manual_periodic'),
                'track_outgoing': StaticField(True),
                'track_incoming': StaticField(True),
                #TODO: add stock level
            },
        },
    },

    'Order': {
        'sale.order': {
            #'amount_total': StdField('sub_total_with_tax().to_eng_string()'),
            #'amount_untaxed': StdField('sub_total.to_eng_string()'),
            #'client_order_ref: NotImplemented,
            'company_id': StaticField(company_id),
            #'currency_id': StaticField(1), #Currency id of your eShop
            #'discount': StdField('item_discount.to_eng_string()')
            'fiscal_position': StaticField(6), #6 for EU customer
            'invoice_quantity': StaticField('order'),
            'name': StaticField('/'), #is generated by OE
            #XXX: change this to fit your order policy
            'order_policy': StaticField('prepaid'),
            'partner_id': ForeignIdField(
                    'contact.billing_address.id', 'AddressBook', 'res.partner'),#XXX
            'partner_invoice_id': ForeignIdField(
                    'contact.billing_address.id', 'AddressBook', 'res.partner'),
            'partner_shipping_id': ForeignIdField(
                    'contact.shipping_address.id', 'AddressBook', 'res.partner'),
            'payment_term': StaticField(1), # 1=immediate payment
            'picking_policy': StaticField('one'),
            'pricelist_id': StaticField(1),
            'shop_id': StaticField(1),
            'state': StaticField('draft'),
        },
    },

    'OrderItem': {
        'sale.order.line': {
            'company_id': StaticField(company_id),
            'name': StdField('description.decode()'),
            #'delay': NotImplemented, #XXX check whether this has to be set here
            #'discount': StdField('discount.to_eng_string()'),
            'order_id': ForeignIdField('order.id', 'Order', 'sale.order'),
            'price_unit': StdField('unit_price_with_tax.to_eng_string()'),
            'product_uom_qty': StdField('quantity.to_eng_string()'),
            'product_uos_qty': StdField('quantity.to_eng_string()'),
            'product_uom': StaticField(1),
            'product_id': ForeignIdField('product_id', 'Product', 'product.product'),
            #'sequence': StaticField(10), #what is this good for?
            'type': StaticField('make_to_stock'),
        },
    },
}


