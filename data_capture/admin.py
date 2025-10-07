# data_capture/admin.py
from django.contrib import admin
from .models import DemandData

admin.site.register(DemandData)