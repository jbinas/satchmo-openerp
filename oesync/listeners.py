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


def on_delete_obj_mapper(sender, instance, **kwargs):

    # prevent possible recursion
    if sender == DeletedObjMapper:
        return

    # search for obj-mappers
    del_mappers = ObjMapper.objects.filter(
        content_type = ContentType.objects.get_for_model(sender),
        object_id = instance.id,
        parent = None)

    #check whether live sync is activated and set sync_now accordingly
    if settings.OPENERP_SETTINGS['MODE'] == 'live':
        _set_attribute(del_mappers, 'sync_now', True)

    #sync...
    res = all(map(_delete_for_mapper, del_mappers))
    log.debug('Sync of \'%s\' finished with result: %s' % (instance, res))



def _delete_for_mapper(mapper, mapping_table=None, parent=None):
    ''' Delete the OE object(s) corresponding to the given mapper '''

    #get model corresponding to specified mapper
    obj_model = mapper.content_type.model_class()

    if mapping_table is None:
        #get root mapping if no mapping is specified
        mapping_table = ModelMapper.get_for_model(obj_model)[mapper.oerp_model]

    res = True

    #copy mapper for future reference
    mapper_del = DeletedObjMapper.objects.get_or_create(
        content_type = mapper.content_type,
        oerp_model = mapper.oerp_model,
        oerp_id = mapper.oerp_id,
        parent = parent)[0]

    #find child mappers
    child_mappers = mapper.__class__.objects.filter(parent = mapper)

    for child in child_mappers:
        #recursively delete child objects
        child.sync_now = mapper.sync_now
        res = res and _delete_for_mapper(
            mapper = child,
            mapping_table = mapping_table[child.oerp_model],
            parent = mapper_del)

    #check whether objects corresponding to this oe model can be deleted
    mapper.auto_del = ModelMapper.check_auto_del(mapping_table)


    try:
        if mapper.sync_now:
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
    except Exception as errmsg:
        #the sync failed
        log.error('Sync failed -- %s' % errmsg)
        mapper_del.is_dirty = True
        res = False
    finally:
        #store mapper in deleted mappers and delete original mapper
        if mapper != mapper_del:
            mapper.delete()
        mapper_del.save()

    return res



def on_save_obj_mapper(sender, instance, **kwargs):

    # prevent possible recursion
    if sender == ObjMapper:
        return

    #The convention here is to always create an object if it cannot be found,
    #rather than only creating it if it has just been created in Satchmo.

    res = True

    #get root mapping since no mapping is specified
    mapping = ModelMapper.get_for_model(sender)

    for oerp_model in mapping.keys():
        # There is no mapper object yet.
        mapper = ObjMapper.objects.get_or_create(
            content_type = ContentType.objects.get_for_model(sender),
            object_id = instance.id,
            oerp_model = oerp_model,
            parent = None)[0]

        #check whether live sync is active
        if settings.OPENERP_SETTINGS['MODE'] == 'live':
            mapper.sync_now = True

        #sync object
        res = res and _save_for_mapper(mapper)

    log.debug('Sync of \'%s\' finished with result: %s' % (instance, res))


def _save_for_mapper(mapper, mapping_table=None):

    #get model corresponding to specified mapper
    obj_model = mapper.content_type.model_class()

    if mapping_table is None:
        #get root mapping if no mapping is specified
        mapping_table = ModelMapper.get_for_model(obj_model)[mapper.oerp_model]

    res = True

    try:
        if mapper.sync_now:
            #The object is synced now

            oerp_object = Oerp(mapper.oerp_model, mapper.oerp_id)

            if oerp_object.exists:
                #object has to be updated
                data_dict = ModelMapper.parse_data(
                    mapper.object,
                    mapping_table,
                    mapper.oerp_model,
                    'update')[0]
                oerp_object.update(data_dict)
            else:
                #create object if it doesn't exist
                data_dict = ModelMapper.parse_data(
                    mapper.object,
                    mapping_table,
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
        children = ModelMapper.get_children(mapping_table)
        for child_model, child_mapping in children.items():
            #create child mapper
            log.debug('Mapping child model (%s)' % child_model)
            child_mapper = ObjMapper.objects.get_or_create(
                parent = mapper,
                content_type = mapper.content_type,
                object_id = mapper.object_id,
                oerp_model = child_model,)[0]
            child_mapper.sync_now = mapper.sync_now

            res = res and _save_for_mapper(child_mapper, child_mapping)

    return res



def on_order_success_mapper(sender, order, **kwargs):
    '''
    Confirm the order and pay the resulting invoice
    '''

    #get object mapper
    try:
        mapper = ObjMapper.objects.get_for_object(order, 'sale.order')
    except ObjMapper.DoesNotExist:
        # There is no mapper yet, something must have gone wrong previously
        log.error('Sync failed -- %s' % 'no mapper was found (order id %s)' % order.id)
        mapper = ObjMapper(object=order, oerp_model='sale.order')
        mapper.save()
        return False
        #stop here.

    if settings.OPENERP_SETTINGS['MODE'] == 'live':
        #validate the order
        _validate_order_for_mapper(mapper)



def _validate_order_for_mapper(order_mapper):

    #reload mapper
    order_mapper = order_mapper.__class__.objects.get(id=order_mapper.id)

    #prepare
    order = order_mapper.object
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




def syncnow(mapper=None, queryset=QuerySet()):
    '''
    Sync unsynced data now
    '''
    #sync single object if mapper is specified
    if isinstance(mapper, DeletedObjMapper):
        #the object has to be deleted
        mapper.sync_now = True
        return _delete_for_mapper(mapper)

    elif isinstance(mapper, ObjMapper):
        #the object has to be created/updated
        try:
            #check whether the order might have to be validated
            validate_order = mapper.validate_order
        except AttributeError:
            #normal sync
            mapper.sync_now = True
            return _save_for_mapper(mapper)
        else:
            #validate the order
            if validate_order and mapper.object.status == 'New':
                return _validate_order_for_mapper(mapper)
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
            ).order_by('date_created', 'id')
        #copy timestamp for comparison
        _copy_attribute(crt_mappers, 'date_created', 'timestamp')

        mod_mappers = mappers_all_upd.filter(
            #objects to be updated
            parent = None,
            is_dirty = True,
            oerp_id__isnull = False,
            ).order_by('date_modified')
        _copy_attribute(mod_mappers, 'date_modified', 'timestamp')

        del_mappers = mappers_all_del.filter(
            #objects to be deleted
            parent = None,
            is_dirty = True
            ).order_by('date_modified')
        _copy_attribute(del_mappers, 'date_modified', 'timestamp')

        ord_mappers = mappers_all_upd.filter(
            #orders that might have to be validated
            parent = None,
            is_dirty = True,
            content_type = ContentType.objects.get(model='order'),
            ).order_by('date_modified')
        _set_attribute(ord_mappers, 'validate_order', True)

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


def _copy_attribute(queryset, attr_old, attr_new):
    for object in queryset:
        object.__setattr__(attr_new, object.__getattribute__(attr_old))

def _set_attribute(queryset, attr_name, value):
    for object in queryset:
        object.__setattr__(attr_name, value)



class PseudoMapper:
    ''' Stores some properties of a deleted object '''
    def __init__(self, sender, instance):
        self.object = instance
        self.oerp_model = None
        self.content_type = ContentType.objects.get_for_model(sender)
