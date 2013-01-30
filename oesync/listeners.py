from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from oesync.models import ObjMapper, DeletedObjMapper
from oesync.oerprpc import Oerp, OerpSyncFailed
from oesync.modelmapper import ModelMapper, MappingError
from datetime import date
import logging

log = logging.getLogger('OESync')




__all__ = [
    'on_delete_obj_mapper',
    'on_save_obj_mapper',
    'on_order_success_mapper'
]


def on_delete_obj_mapper(sender, instance, mapping=None, **kwargs):

    # prevent possible recursion
    if sender == ObjMapper:
        return

    # prepare
    inst_id = instance.id
    content_type = ContentType.objects.get_for_model(sender)

    if mapping is None:
        #get root mapping if no mapping is specified
        mapping = ModelMapper.get_for_model(sender)

    for oerp_model, oerp_fields in mapping.items():

        #find child models of this model
        children = ModelMapper.get_children(oerp_fields)
        if children:
            #recursively delete child objects
            on_delete_obj_mapper(sender=sender, instance=instance, mapping=children)

        # search for obj-mappers
        obj_mappers = ObjMapper.objects.filter(
            content_type = content_type,
            object_id = inst_id,
            oerp_model = oerp_model)

        # delete mappers
        for mapper in obj_mappers:
            #copy mapper for future reference
            mapper_del = DeletedObjMapper(
                content_type = mapper.content_type,
                oerp_model = mapper.oerp_model,
                oerp_id = mapper.oerp_id)
            try:
                oerp_object = Oerp(oerp_model, mapper.oerp_id)

                #only try to delete if the object exists and is not
                #deleted automatically with its parent object
                if oerp_object.exists and not ModelMapper.check_auto_del(oerp_fields):
                    oerp_object.delete()
                #deleting non-existent objects is OK and is not logged
                mapper_del.is_dirty = False
            except Exception as errmsg:
                #the sync failed
                log.error('Sync failed -- %s' % errmsg)
                mapper_del.is_dirty = True
            finally:
                #store mapper in deleted mappers and delete mapper
                mapper_del.save()
                mapper.delete()



def on_save_obj_mapper(sender, instance, mapping=None, **kwargs):

    # prevent possible recursion
    if sender == ObjMapper:
        return

    #The convention here is to always create an object if it cannot be found,
    #rather than only creating it if it has just been created in Satchmo.

    if mapping is None:
        #get root models if no mapping is specified
        mapping = ModelMapper.get_for_model(sender)

    for oerp_model, oerp_fields in mapping.items():
        try:
            mapper = ObjMapper.objects.get_for_object(instance, oerp_model)
        except ObjMapper.DoesNotExist:
            # There is no mapper object yet.
            mapper = ObjMapper(object=instance, oerp_model=oerp_model)

        try:
            oerp_object = Oerp(oerp_model, mapper.oerp_id)

            if oerp_object.exists:
                #object has to be updated
                data_dict,children = ModelMapper.parse_data(
                    instance,
                    oerp_fields,
                    oerp_model,
                    'update')
                oerp_object.update(data_dict)
            else:
                #create entry if no corresponding object exists
                data_dict,children = ModelMapper.parse_data(
                    instance,
                    oerp_fields,
                    oerp_model,
                    'create')
                oerp_object.create(data_dict)

                #update mapper
                mapper.oerp_id = oerp_object.id

        except MappingError as errmsg:
            log.error('Sync failed -- %s' % errmsg)
            mapper.save_state('dirty')

        except OerpSyncFailed as errmsg:
            log.error('Sync failed -- %s' % errmsg)
            mapper.save_state('dirty')

        else:
            #sync was successful
            mapper.save_state('clean')

            #run this recursively if child mappings are found
            if children:
                on_save_obj_mapper(sender, instance, children)



def on_order_success_mapper(sender, order, **kwargs):
    '''
    Confirm the order and pay the resulting invoice
    '''

    #get object mapper
    try:
        order_mapper = ObjMapper.objects.get_for_object(order, 'sale.order')
    except ObjMapper.DoesNotExist:
        # There is no mapper object yet, something must have gone wrong
        # previously
        log.error('Sync failed -- %s' % 'no mapper was found (order id %s)' % order.id)
        order_mapper = ObjMapper(object=order, oerp_model='sale.order')
        order_mapper.save()
        return False
        #stop here.

    order_model = Oerp('sale.order', order_mapper.oerp_id)

    #try to confirm the order
    try:
        order_model.confirm_order()
        #get id of the invoice for this order
        #it should be OK to only consider the last invoice since it has
        #just been created
        invoice_id = order_model.read(['invoice_ids'])['invoice_ids'][-1]

        order_mapper.save_state('clean')

    except OerpSyncFailed as errmsg:
        #Something went wrong
        order_mapper.save_state('dirty')
        log.error('Sync failed -- %s' % errmsg)
        return False

    except KeyError:
        #The invoice doesn't seem to exist
        order_mapper.save_state('dirty')
        log.error('Sync failed -- Invoice doesn\'t exist (order id %s)' % order.id)
        return False

    #sync payments
    try:
        #confirm the invoice
        confirm_invoice_model = Oerp('account.invoice.confirm')
        confirm_invoice_model.validate_invoice(invoice_id)
    except:
        #the invoice could not be confirmed
        log.error('Sync failed -- Invoice couldn\'t be confirmed (%s)' % invoice_id)
        return False


    voucher_model = Oerp('account.voucher')

    #try adding payments to invoice
    for payment in order.payments_completed():
        try:
            #create object mapper
            payment_mapper = ObjMapper(object=payment, oerp_model='account.voucher')
            partner_mapper = ObjMapper.objects.get_for_object(
                                order.contact.billing_address, 'res.partner')
            #add payment
            voucher_model.add_payment(
                partner_id = partner_mapper.oerp_id,
                account_id = settings.OPENERP_SETTINGS['ACCOUNT_ID'],
                journal_id = settings.OPENERP_SETTINGS['JOURNAL_ID'],
                period_id = date.today().month,
                amount = float(payment.amount),
                company_id = settings.OPENERP_SETTINGS['COMPANY_ID'],
                currency_id = settings.OPENERP_SETTINGS['CURRENCY_ID'],
            )
            payment_mapper.oerp_id = voucher_model.id
            payment_mapper.save_state('clean')

        except Exception as e:
            #The creation failed
            payment_mapper.save_state('dirty')
            log.error('Sync failed -- %s' % errmsg)



def _set_mapper_state(mapper, state='dirty'):
    if state is 'dirty':
        is_dirty = True
    else:
        is_dirty = False
    mapper.is_dirty = is_dirty
    mapper.save()
