from django.contrib.contenttypes.models import ContentType
from django.conf import settings
from django.db.models.signals import pre_delete, post_save
from oesync.signals import post_save_all
from satchmo_store.shop.signals import order_success
#from signals_ahoy.signals import form_init, form_postsave
from oesync.listeners import *
from oesync.modelmapper import ModelMapper



_contain_inline = ModelMapper.access_inline

_objmap_models = [
    ContentType.objects.get(model=model_name.lower()).model_class() \
    for model_name in ModelMapper.mapping.keys() if model_name not in _contain_inline]

_objmap_models_inline = [
    ContentType.objects.get(model=model_name.lower()).model_class() \
    for model_name in _contain_inline]


# Signal registering.
def _reg_signal(signal, method):
    '''Return method for registering signals.'''
    def _method(model):
        signal.connect(method, sender=model)
    return _method



map(_reg_signal(pre_delete, on_delete_obj_mapper), _objmap_models+_objmap_models_inline)
map(_reg_signal(post_save, on_save_obj_mapper), _objmap_models)
map(_reg_signal(post_save_all, on_save_obj_mapper), _objmap_models_inline)

if settings.OPENERP_SETTINGS['ORDER_ACTION']:
    #special order_success action
    order_success.connect(on_order_success_mapper)
