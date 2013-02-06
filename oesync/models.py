from django.db import models
import time
from django.contrib.contenttypes import generic
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import ugettext_lazy as _




class ObjMapperManager(models.Manager):
    '''
    Special manager.
    '''

    def get_for_object(self, instance, oerp_model, parent=None):
        '''
        resolves the obj_mapper for a given model-instance
        '''
        content_type = ContentType.objects.get_for_model(instance.__class__)
        return self.get(
            content_type=content_type,
            object_id=instance.id,
            oerp_model = oerp_model,
            parent = parent)

    def get_for_oerp_id(self, oerp_id, oerp_model, model):
        content_type = ContentType.objects.get_for_model(model)
        return self.get(
            oerp_id = oerp_id,
            content_type = content_type)


class ObjMapper(models.Model):
    '''
    Holds the relationship between a Satchmo object and an OpenERP object.
    '''

    date_created = models.DateTimeField(
        _('date created'), default=models.datetime.datetime.now(), null=False,
        blank=False)
    date_modified = models.DateTimeField(
        _('date modified'), default=models.datetime.datetime.now(),
        null=False, blank=False)
    timestamp_created = models.BigIntegerField(
        _('timestamp created'), default = time.time()*1e6, null=False)
    timestamp_modified = models.BigIntegerField(
        _('timestamp modified'), default = time.time()*1e6, null=False)
    is_dirty = models.BooleanField(default=True)
    oerp_id = models.PositiveIntegerField(
        _('OpenERP Id'), null=True, blank=True)
    content_type = models.ForeignKey(ContentType, verbose_name='Content Type')
    oerp_model = models.CharField(max_length=128, verbose_name='OpenERP Model')
    object_id = models.PositiveIntegerField(_('Object Id'), db_index=True)
    parent = models.ForeignKey('self', null=True, blank=True)
    object = generic.GenericForeignKey('content_type', 'object_id')
    objects = ObjMapperManager()

    def save_state(self, state='dirty'):
        if state is 'dirty':
            self.is_dirty = True
        else:
            self.is_dirty = False
        self.save()

    def save(self, *args, **kwargs):
        ''' Update timestamp '''
        if not self.id:
            self.timestamp_created = time.time()*1e6
        self.timestamp_modified = time.time()*1e6
        super(ObjMapper, self).save(*args, **kwargs)


    class Meta:
        verbose_name = _('Object Mapper')
        verbose_name_plural = _('Object Mappers')
        ordering = ('content_type', )

    def __unicode__(self):
        return u'%s' % self.object



class DeletedObjMapper(models.Model):
    '''
    Stores deleted object mappers for reference
    '''

    date_created = models.DateTimeField(
        _('date created'), default=models.datetime.datetime.now(), null=False,
        blank=False)
    date_modified = models.DateTimeField(
        _('date modified'), default=models.datetime.datetime.now(),
        null=False, blank=False)
    timestamp_created = models.BigIntegerField(
        _('timestamp created'), default = time.time()*1e6, null=False)
    timestamp_modified = models.BigIntegerField(
        _('timestamp modified'), default = time.time()*1e6, null=False)
    is_dirty = models.BooleanField(default=True)
    parent = models.ForeignKey('self', null=True, blank=True)
    oerp_id = models.PositiveIntegerField(
        _('OpenERP Id'), null=True, blank=True)
    content_type = models.ForeignKey(ContentType, verbose_name='Content Type')
    oerp_model = models.CharField(max_length=128, verbose_name='OpenERP Model')

    def save(self, *args, **kwargs):
        ''' Update timestamp '''
        if not self.id:
            self.timestamp_created = time.time()*1e6
        self.timestamp_modified = time.time()*1e6
        super(DeletedObjMapper, self).save(*args, **kwargs)

    class Meta:
        verbose_name = _('Deleted Object Mapper')
        verbose_name_plural = _('Deleted Object Mappers')
        ordering = ('content_type', )

    def __unicode__(self):
        return u'Deleted Mapper (%s)' % self.content_type
