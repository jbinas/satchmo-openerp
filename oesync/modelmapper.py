from oesync.fields import *
import oesync.mapping_config as mapping
import logging

log = logging.getLogger('OESync')



class ModelMapper:

    def __init__(self, content_type=None):

        self.mapping = mapping.mapping

        self._protected_tags = [
            '_AUTO_DELETE',
            '_ACCESS_INLINE',
            '_ADMIN_CLASS',
        ]

        # The following models will be equipped with a special signal
        # that allows access of inline child objects when they are saved in
        # admin. This is necessary for 'Product', for example.
        self.access_inline = self._get_access_inline_models()


    def _get_access_inline_models(self):
        models = []
        for model, mapping in self.mapping.items():
            try:
                if mapping['_ACCESS_INLINE']:
                    models.append(model)
            except KeyError:
                pass
        return models


    def get_for_model(self, satchmo_model=None):
        '''
        Return mapping corresponding to given Satchmo model.
        '''
        try:
            mapping = self.mapping[satchmo_model.__name__]
            #return mappings only (no special tags)
            return self.get_children(mapping)
        except KeyError:
            log.warning('No mapping could be found for model \'%s\'' % satchmo_model)
            return {}
            #raise MappingError('There is no mapping for this model')

    def get_model(self, model_name):
        return ContentType.objects.get(model=model_name.lower()).model_class()
        #TODO: add exception here

    def get_for_oerp_model(self, oerp_model=None):
        '''
        Return corresponding Satchmo model name.
        '''
        return NotImplemented #FIXME
        #try:
        #    return (key for key,value in self.mapping.items() \
        #        if value['oe_model']==oerp_model).next()
        #except StopIteration:
        #    raise MappingError('There is no mapping for this model')

    def get_children(self, mapping):
        '''
        Finds child models (and their mapping) of given mapping
        '''
        children = {}
        for oerp_field, satchmo_field in mapping.items():
            if isinstance(satchmo_field, dict):
                children[oerp_field] = satchmo_field
        return children

    def get_for_ctype(self, content_type):
        '''
        Return OpenErp model name for given content type
        '''
        return NotImplemented

    def parse_data(self, instance, mapping, oerp_model, action=None):
        '''
        Converts Satchmo fields to OpenErp fields and returns data dictionary
        '''
        data = {}
        children = {}
        if mapping is None:
            raise MappingError('No mapping was specified')
        #loop though fields of mapping
        for oerp_field, satchmo_field in mapping.items():
            if isinstance(satchmo_field, dict):
                #mapping of a child model was found
                children[oerp_field] = satchmo_field
            elif oerp_field not in self._protected_tags:
                #normal field-to-field mapping
                try:
                    #only map field if current action is specified in field actions
                    if action in satchmo_field.actions:
                        #get field data
                        data[oerp_field] = satchmo_field.get_content(instance, oerp_model)
                except Exception as e:
                    raise MappingError(
                        'An error occured while mapping content %s: %s -- %s' % \
                        (oerp_field, satchmo_field, e))
        return (data, children)

    def check_auto_del(self, mapping):
        ''' Check whether a (child) object can be deleted '''
        # some models, e.g. product.template, only allow unlinking of
        # the root object -- children are deleted automatically
        try:
            return mapping['_AUTO_DELETE']
        except KeyError:
            return False






class MappingError(Exception):
    def __init__(self, msg=None):
        self.msg = msg
    def __str__(self):
        return self.msg



#return instance rather than class
ModelMapper = ModelMapper()


