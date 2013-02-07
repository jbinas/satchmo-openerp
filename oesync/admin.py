from django.contrib import admin
from django.contrib import messages
from oesync.models import ObjMapper, DeletedObjMapper
from oesync.modelmapper import ModelMapper
from oesync.signals import post_save_all
from oesync.listeners import syncnow
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import ugettext_lazy as _
import re



#import admin classes to be patched
model_admin_classes = []
for model_name in ModelMapper.access_inline:
    module_path,class_name = re.search(
        '^(.*?)\.?([a-zA-Z0-9_]+)$',
        ModelMapper.mapping[model_name]['_ADMIN_CLASS']).group(1,2)
    #import...
    if module_path:
        exec('from %s import %s' % (module_path, class_name))
    else:
        exec('import %s' % class_name)
    #store classes for later use
    model_class = ContentType.objects.get(model=model_name.lower()).model_class()
    admin_class = eval(class_name)
    model_admin_classes.append((model_class, admin_class))



def _sync_selected(modeladmin, request, queryset):
    ''' Admin action to sync selected objects '''
    if syncnow(queryset=queryset):
        messages.info(request, _('%s objects were successfully synced.' % len(queryset)))
    else:
        messages.error(request, _('An error occured. Not all objects could be synced.'))
_sync_selected.short_description = _('Synchronize selected objects')


class ObjMapperAdmin(admin.ModelAdmin):
    list_display = ('object','content_type', 'object_id', 'parent', 'oerp_model', 'oerp_id', 'is_dirty')
    list_display_links = ('object', 'content_type')
    list_filter = ('content_type', )
    actions = ['sync_selected']
    search_fields = ['content_type', 'oerp_model']
    ordering = ['-is_dirty']
    #if config_value('LANGUAGE','SHOW_TRANSLATIONS'):
    #filter_vertical = ('content_type',)
    sync_selected = _sync_selected

admin.site.register(ObjMapper, ObjMapperAdmin)



class DeletedObjMapperAdmin(admin.ModelAdmin):
    list_display = ('content_type', 'parent', 'oerp_model', 'oerp_id', 'is_dirty')
    list_display_links = ('oerp_model', 'oerp_id')
    list_filter = ('content_type', )
    actions = ['sync_selected']
    ordering = ['-is_dirty']
    search_fields = ['content_type', 'oerp_model']
    sync_selected = _sync_selected

admin.site.register(DeletedObjMapper, DeletedObjMapperAdmin)





# Patch admin classes to dispatch custom signal once all child
# objects have been saved (some child objects cannot be accessed
# right away if the std. post_save signal is used)

for model_class,admin_class in model_admin_classes:

    admin.site.unregister(model_class)

    class ModelAdminExtension(admin_class):

       def save_related(self, request, form, formsets, change):

            form.save_m2m()
            for formset in formsets:
                self.save_formset(request, form, formset, change=change)

            instance = form.instance
            created = not change
            #dispatch signal
            post_save_all.send(
                sender=instance.__class__,
                instance=instance,
                created=created)

    admin.site.register(model_class, ModelAdminExtension)
