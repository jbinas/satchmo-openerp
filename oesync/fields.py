from oesync.models import ObjMapper
from django.contrib.contenttypes.models import ContentType
import logging

log = logging.getLogger('OESync')


class GetField(object):
    '''
    Base class
    '''
    def __init__(self, attr_name, param_name=None,
            default=None, actions=['create','update']):
        self.attr_name = attr_name
        self.param_name = param_name
        self.actions = actions
        self.default = default

    def __str__(self):
        return self.attr_name

    def _check(self, value):
        ''' convert empty strings/None to False (NoneType is not supported in XMLRPC)'''
        if value in (None, '', u'', []):
            return False
        elif isinstance(value, list):
            return [(6,0,value)] #format value to comply with OpenErp m2m format
            # OE many2many fields have to be modified as follows:
            # Values: (0, 0, { fields }) create
            # (1, ID, { fields }) modification
            # (2, ID) remove
            # (3, ID) unlink
            # (4, ID) link
            # (5, ID) unlink all
            # (6, ?, ids) set a list of links
        return value

    def _get_value(self, instance):
        ''' return value of specified field '''
        try:
            return eval("instance.%s" % self.attr_name)
        except Exception as e:
            #check whether default value is set
            if self.default is not None:
                return self.default
            raise Exception

    def _get_m2m_ids(self, instance):
        ''' Return multiple ids of instances of related model '''
        all_inst = eval("instance.%s.all()" % self.attr_name)
        ids = [inst.id for inst in all_inst]
        return ids

    def _get_inst_ctype(self, instance):
        ''' return content-type for given instance '''
        return ContentType.objects.get_for_model(instance.__class__)

    def _get_model_ctype(self, model_name):
        ''' return content-type for given model name '''
        return ContentType.objects.get(model=model_name.lower())

    def _get_oerp_id(self, content_type, id, oe_model):
        ''' return oerp_id for given content-type and id '''
        try:
            mapper = ObjMapper.objects.get(
                content_type=content_type,
                object_id=id,
                oerp_model=oe_model)
        except ObjMapper.DoesNotExist:
            #XXX: Should we not allow syncing if oerp_id is unknown?
            log.warning('No mapper could be found for %s (%s)...' % \
                (content_type.name,id))
        else:
            return mapper.oerp_id
        return None

    def get_content(self, instance, oe_model, create):
        return NotImplemented




class StdField(GetField):
    ''' Returns the instance attribute corresponding to attr_name. '''
    def get_content(self, instance, oe_model):
        return self._check(self._get_value(instance))


class IdField(GetField):
    ''' Returns the oerp_id corresponding to a given model field. '''
    def get_content(self, instance, oe_model):
        inst_id = self._get_value(instance)
        content_type = self._get_inst_ctype(instance)
        if self.param_name:
            #get id for a different oe model if specified
            oe_model = self.param_name
        return self._check(self._get_oerp_id(content_type, inst_id, oe_model))


class ForeignIdField(GetField):
    ''' Returns oerp_id of related model object provided as second argument '''
    def __init__(self, attr_name, param_name, foreign_oe_model=None, default=None,
                actions=['create','update']):
        self.foreign_oe_model = foreign_oe_model
        super(ForeignIdField, self).__init__(attr_name, param_name, default, actions)

    def get_content(self, instance, oe_model):
        foreign_id = self._get_value(instance)
        content_type = self._get_model_ctype(self.param_name)
        if self.foreign_oe_model:
            #get id for a different oe model if specified
            oe_model = self.foreign_oe_model
        return self._check(self._get_oerp_id(content_type, foreign_id, oe_model))


class ManyForeignIdField(GetField):
    ''' Returns ids of m2m related objects '''
    def __init__(self, attr_name, param_name, foreign_oe_model=None, default=None,
                actions=['create','update']):
        self.foreign_oe_model = foreign_oe_model
        super(ManyForeignIdField, self).__init__(attr_name, param_name, default, actions)

    def get_content(self, instance, oe_model):
        foreign_ids = self._get_m2m_ids(instance)
        content_type = self._get_model_ctype(self.param_name)
        if self.foreign_oe_model:
            #get id for a different oe model if specified
            oe_model = self.foreign_oe_model
        oe_ids = []
        for id in foreign_ids:
            oe_id = self._get_oerp_id(content_type, id, oe_model)
            if oe_id: oe_ids.append(oe_id)
        return self._check(oe_ids)


class BoolField(GetField):
    ''' Check whether field content has specific value '''
    def get_content(self, instance, oe_model):
        if self.param_name is None:
            #FIXME: This will not allow to check whether a field is None...
            self.param_name = True
        return self._check(self.param_name == self._get_value(instance))


class StaticField(GetField):
    def __init__(self, value, actions=['create']):
        self.value = value
        super(StaticField, self).__init__(value, actions=actions)
    def get_content(self, instance, oe_model):
        return self._check(self.value)


class SelectionField(GetField):
    def get_content(self, instance, oe_model):
        value = self._get_value(instance)
        try:
            return self._check(self.param_name[value])
        except KeyError:
            try:
                return self._check(self.param_name['_default'])
            except KeyError:
                return False


