# data_capture/urls.py

from django.urls import path
from . import views

urlpatterns = [
    # The empty path '' makes this the default page for the app
    path('', views.show_all_data_homepage, name='homepage'),
]