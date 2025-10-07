from django.db import models
from django.utils import timezone

class DemandData(models.Model):
    # Existing fields
    current_demand = models.CharField(
        max_length=50, 
        help_text="Current demand value in MW"
    )
    yesterday_demand = models.CharField(
        max_length=50, 
        help_text="Yesterday's demand value in MW"
    )
    
    # NEW: Field for the time block string, e.g., "10:15 - 10:30"
    time_block = models.CharField(
        max_length=50,
        help_text="The time block string extracted from the site",
        null=True,
        blank=True
    )
    
    # NEW: Field for just the date from the site
    date = models.DateField(
        help_text="The date extracted from the website",
        null=True,
        blank=True
    )
    
    # Timestamp for when the script ran
    captured_at = models.DateTimeField(
        default=timezone.now, 
        help_text="Timestamp of when the data was captured"
    )

    def __str__(self):
        local_time = timezone.localtime(self.captured_at)
        return f"Data captured at {local_time.strftime('%Y-%m-%d %H:%M:%S %Z')}"

    class Meta:
        ordering = ['-captured_at']