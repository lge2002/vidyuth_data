# data_capture/views.py

from django.shortcuts import render
from .models import DemandData

def show_all_data_homepage(request):
    """
    This view now fetches ONLY the latest DemandData object.
    """
    # ❗ CHANGE: Get the single most recent object instead of all of them.
    latest_data = DemandData.objects.order_by('-id').first() 
    
    context = {
        # ❗ CHANGE: Pass the single object to the template.
        'latest_data': latest_data  
    }
    
    return render(request, 'data_capture/latest_data.html', context)