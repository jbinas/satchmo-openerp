from django.contrib.contenttypes.models import ContentType
from django.db.models.query import QuerySet
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


def on_delete_obj_mapper(sender=None, instance=None, mapping=None, **kwargs):

    # prevent possible recursion
    if sender == DeletedObjMapper:
        return

    if instance is None:
        #nothing to do here
        return

    if sender is None:
        #no sender is specified (this has been called manually and instance is a mapper)
        sender = instance.content_type.model_class()

    if mapping is None:
        #get root mapping if no mapping is specified
        mapping = ModelMapper.get_for_model(sender)

    res = True

    for oerp_model, oerp_fields in mapping.items():

        #check whether objects corresponding to this model can be deleted
        auto_del = ModelMapper.check_auto_del(oerp_fields)

        #find child models of this model
        children = ModelMapper.get_children(oerp_fields)
        if children:
            #recursively delete child objects
            res = res and on_delete_obj_mapper(
                sender=sender,
                instance=instance,
                mapping=children)

        if isinstance(instance, DeletedObjMapper):
            #a single mapper is specified, deletion can be called directly
            instance.auto_del = auto_del
            res = res and _delete_for_mapper(instance)

        else:
            # search for obj-mappers
            obj_mappers = ObjMapper.objects.filter(
                content_type = ContentType.objects.get_for_model(sender),
                object_id = instance.id,
                oerp_model = oerp_model)

            # delete objects
            for mapper in obj_mappers:
                mapper.auto_del = auto_del #add this temporarily
                res = res and _delete_for_mapper(
                    mapper,
                    settings.OPENERP_SETTINGS['AUTOSYNC'])
    return res


def _delete_for_mapper(mapper, deletenow=True):
    ''' Delete the OE object corresponding to the given mapper '''
    #copy mapper for future reference
    mapper_del = DeletedObjMapper(
        content_type = mapper.content_type,
        oerp_model = mapper.oerp_model,
        oerp_id = mapper.oerp_id,
        parent = mapper.parent)
    try:
        if deletenow:
            #Automatic synchronization is turned on
            oerp_object = Oerp(mapper.oerp_model, mapper.oerp_id)

            #only try to delete if the object exists and is not
            #deleted automatically with its parent object
            if oerp_object.exists and not mapper.auto_del:
                oerp_object.delete()
            #deleting non-existent objects is OK and is not logged
            mapper_del.is_dirty = False
        else:
            #this object will be deleted later
            mapper_del.is_dirty = True
        res = True #sync was successful
    except Exception as errmsg:
        #the sync failed
        log.error('Sync failed -- %s' % errmsg)
        mapper_del.is_dirty = True
        res = False
    finally:
        #store mapper in deleted mappers and delete mapper
        mapper.delete()
        mapper_del.save()
        return res



def on_save_obj_mapper(sender=None, instance=None, mapping=None, \
                       parent=None, syncnow=False, **kwargs):

    # prevent possible recursion
    if sender == ObjMapper:
        return

    if instance is None:
        return

    if isinstance(instance, ObjMapper):
        #this has been called manually
        sender = instance.content_type.model_class()
        instance = instance.object
        syncnow = True

    #The convention here is to always create an object if it cannot be found,
    #rather than only creating it if it has just been created in Satchmo.

    res = True

    if mapping is None:
        #get root models if no mapping is specified
        mapping = ModelMapper.get_for_model(sender)

    for oerp_model, oerp_fields in mapping.items():
        try:
            mapper = ObjMapper.objects.get_for_object(instance, oerp_model, parent)
        except ObjMapper.DoesNotExist:
            # There is no mapper object yet.
            mapper = ObjMapper(
                object = instance,
                oerp_model = oerp_model,
                parent = parent)

        try:
            if syncnow or settings.OPENERP_SETTINGS['AUTOSYNC']:
                #The object is synced now

                oerp_object = Oerp(mapper.oerp_model, mapper.oerp_id)

                if oerp_object.exists:
                    #object has to be updated
                    data_dict = ModelMapper.parse_data(
                        mapper.object,
                        oerp_fields,
                        mapper.oerp_model,
                        'update')[0]
                    oerp_object.update(data_dict)
                else:
                    #create object if it doesn't exist
                    data_dict = ModelMapper.parse_data(
                        mapper.object,
                        oerp_fields,
                        mapper.oerp_model,
                        'create')[0]
                    oerp_object.create(data_dict)

                    #update mapper
                    mapper.oerp_id = oerp_object.id

                #consider sync successful if we get to this point
                mapper.save_state('clean')

            else:
                #This object is synced later. Only change mapper status...
                mapper.save_state('dirty')

        except MappingError as errmsg:
            log.error('Sync failed -- %s' % errmsg)
            mapper.save_state('dirty')
            res = False

        except OerpSyncFailed as errmsg:
            log.error('Sync failed -- %s' % errmsg)
            mapper.save_state('dirty')
            res = False

        else:
            #the sync was successful
            #run this recursively if child mappings are found
            children = ModelMapper.get_children(oerp_fields)
            if children:
                res = res and on_save_obj_mapper(
                    sender,
                    instance,
                    children,
                    mapper,
                    syncnow)

    return res



def on_order_success_mapper(sender, order, syncnow=False, **kwargs):
    '''
    Confirm the order and pay the resulting invoice
    '''

    if isinstance(order, ObjMapper):
        #this has been called manually and order is a mapper object
        sender = order.content_type.model_class()
        order = order.object
        syncnow = True

    if not settings.OPENERP_SETTINGS['AUTOSYNC'] and not syncnow:
        return

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

    res = True
    voucher_model = Oerp('account.voucher')

    #try adding payments to invoice
    for payment in order.payments_completed():
        try:
            #create payment object mapper
            payment_mapper = ObjMapper(object=payment, oerp_model='account.voucher')
            #load partner object mapper
            partner_mapper = ObjMapper.objects.get_for_object(
                                order.contact.billing_address, 'res.partner')
            #add payment
            voucher_model.add_payment(
                partner_id = partner_mapper.oerp_id,
                account_id = settings.OPENERP_SETTINGS['ACCOUNT_ID'],
                journal_id = settings.OPENERP_SETTINGS['JOURNAL_ID'],
                period_id = date.today().month, #FIXME: find a better solution here
                amount = float(payment.amount),
                company_id = settings.OPENERP_SETTINGS['COMPANY_ID'],
                currency_id = settings.OPENERP_SETTINGS['CURRENCY_ID'],
            )
            payment_mapper.oerp_id = voucher_model.id
            payment_mapper.save_state('clean')

        except Exception as e:
            #The creation failed
            payment_mapper.save_state('dirty')
            log.error('Sync failed -- %s' % e)
            res = False

    return res



def _set_mapper_state(mapper, state='dirty'):
    ''' Set state and save mapper '''
    if state == 'dirty':
        is_dirty = True
    else:
        is_dirty = False
    mapper.is_dirty = is_dirty
    mapper.save()


def syncnow(mapper=None, queryset=QuerySet()):
    '''
    Sync unsynced data now
    '''
    #sync single object if mapper is specified
    if isinstance(mapper, DeletedObjMapper):
        #the object has to be deleted
        return on_delete_obj_mapper(None, mapper)

    elif isinstance(mapper, ObjMapper):
        #the object has to be created/updated
        try:
            #check whether this order has to be validated
            validate_order = mapper.validate_order
        except AttributeError:
            #normal sync
            return on_save_obj_mapper(None, mapper)
        else:
            #validate the order
            if validate_order and mapper.object.status == 'New':
                return on_order_success_mapper(None, mapper)
            else:
                #nothing to be done
                return True
    else:
        #no mapper specified -> sync everything unsynced
        #first, check whether a queryset has been specified via admin
        if queryset.model is ObjMapper:
            #ObjMapper queryset is specified
            mappers_all_upd = queryset
            mappers_all_del = ObjMapper.objects.none() #empty queryset
        elif queryset.model is DeletedObjMapper:
            #DeletedObjMapper queryset is specified
            mappers_all_upd = ObjMapper.objects.none()
            mappers_all_del = queryset
        else:
            #no queryset is specified
            mappers_all_upd = ObjMapper.objects.all()
            mappers_all_del = DeletedObjMapper.objects.all()

        crt_mappers = mappers_all_upd.filter(
            #objects to be created
            parent = None,
            is_dirty = True,
            oerp_id = None,
            ).order_by('timestamp_created', 'id')
        #copy timestamp for comparison
        _copy_timestamp(crt_mappers, 'timestamp_created')

        mod_mappers = mappers_all_upd.filter(
            #objects to be updated
            parent = None,
            is_dirty = True,
            oerp_id__isnull = False,
            ).order_by('timestamp_modified')
        _copy_timestamp(mod_mappers, 'timestamp_modified')

        del_mappers = mappers_all_del.filter(
            #objects to be deleted
            parent = None,
            is_dirty = True
            ).order_by('timestamp_modified')
        _copy_timestamp(del_mappers, 'timestamp_modified')

        ord_mappers = mappers_all_upd.filter(
            #orders that might have to be validated
            parent = None,
            is_dirty = True,
            content_type = ContentType.objects.get(model='order'),
            ).order_by('timestamp_modified')
        _add_validate_order(ord_mappers)

        #merge-sort mappers to synchronize objects in the right order
        mappers = _mergesort(del_mappers, _mergesort(crt_mappers, mod_mappers))

        #run sync
        log.info('Syncing %s objects...' % (len(mappers) + len(ord_mappers)))
        res = all(map(syncnow, mappers))
        return res and all(map(syncnow, ord_mappers))


def _mergesort(set1, set2):
    ''' Mergesort two querysets by timestamp. In the case of equality, set1 dominates '''
    mappers = []
    while len(set1) or len(set2):
        if len(set1) == 0 or (len(set2) and set2[0].timestamp < set1[0].timestamp):
            #del_mapper is older
            mappers.append(set2[0])
            set2 = set2[1:]
        else:
            mappers.append(set1[0])
            set1 = set1[1:]
    return mappers


def _copy_timestamp(queryset, attr_name):
    for object in queryset:
        object.timestamp = object.__getattribute__(attr_name)

def _add_validate_order(queryset):
    for object in queryset:
        object.validate_order = True



class PseudoMapper:
    ''' Stores some properties of a deleted object '''
    def __init__(self, mapper):
        self.id = mapper.object_id
