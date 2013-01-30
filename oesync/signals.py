
from django.dispatch import Signal

post_save_all = Signal(providing_args=['instance', 'created'])
