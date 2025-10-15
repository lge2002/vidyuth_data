from django.urls import path
from . import views

urlpatterns = [
    # The URL for the main HTML page
    path('', views.show_all_data_homepage, name='home'),
    
    # ➕ The new URL for our JSON data endpoint
    path('api/latest-data/', views.latest_data_json, name='latest_data_json'),
]