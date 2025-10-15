# data_capture/management/commands/capture_demand_data.py

import time
import os
import re 
import requests
from urllib.parse import urlencode
from datetime import datetime
from django.core.management.base import BaseCommand
from django.db import transaction
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from data_capture.models import DemandData

class Command(BaseCommand):
    """
    A Django management command that continuously captures power demand data, a time block,
    and a screenshot from the Vidyut PRAVAH website.
    """
    help = "Saves data and a screenshot to the database in a continuous loop."

    def handle(self, *args, **options):
        # --- Configuration ---
        TARGET_URL = "https://vidyutpravah.in/state-data/tamil-nadu"
        API_ENDPOINT = "http://172.16.7.118:8003/api/tamilnadu/demand/post.demand.php"
        WAIT_TIME_SECONDS = 300
        XPATH_CURRENT = '//*[@id="TamilNadu_map"]/div[6]/span/span'
        XPATH_YESTERDAY = '//*[@id="TamilNadu_map"]/div[4]/span/span'
        XPATH_TIME_BLOCK = '/html/body/table/tbody/tr[1]/td/table/tbody/tr[2]/td/table/tbody/tr/td[2]'
        SCREENSHOT_DIR = "screenshots"
        
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        # ---------------------

        try:
            while True:
                start_time = time.monotonic()
                run_start_time = datetime.now()
                formatted_start_time = run_start_time.strftime("%Y-%m-%d %H:%M:%S")
                self.stdout.write(self.style.SUCCESS(f"\n🚀 Starting data capture process at {formatted_start_time}..."))

                current_text = None
                yesterday_text = None
                parsed_time_block = None 
                parsed_date_obj = None
                api_status = "UnknownError"

                # --- Block 1: Data Extraction and Processing ---
                try:
                    # ... (The entire playwright block remains unchanged) ...
                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=True)
                        page = browser.new_page(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/108.0.0.0 Safari/537.36")
                        page.set_viewport_size({"width": 1920, "height": 1080})
                        self.stdout.write(f"Navigating to: {TARGET_URL}")
                        
                        page.goto(TARGET_URL, timeout=90000, wait_until='domcontentloaded')
                        
                        self.stdout.write("Page loaded. Waiting for data elements to become visible...")
                        page.wait_for_selector(f'xpath={XPATH_CURRENT}', state='visible', timeout=30000)
                        self.stdout.write("Data elements are visible. Proceeding with extraction.")
                        
                        current_text = page.locator(f'xpath={XPATH_CURRENT}').inner_text(timeout=10000)
                        yesterday_text = page.locator(f'xpath={XPATH_YESTERDAY}').inner_text(timeout=10000)
                        full_text = page.locator(f'xpath={XPATH_TIME_BLOCK}').inner_text(timeout=10000)
                        
                        self.stdout.write(self.style.SUCCESS(f"✅ Extracted Demand -> Current: {current_text} | Yesterday: {yesterday_text}"))
                        self.stdout.write(self.style.SUCCESS(f"✅ Full Text -> {full_text}"))

                        try:
                            full_text = " ".join(full_text.split())
                            pattern = r"TIME BLOCK (\d{2}:\d{2} - \d{2}:\d{2}) DATED (\d{2} [A-Z]{3} \d{4})"
                            match = re.search(pattern, full_text)
                            
                            if match:
                                parsed_time_block = match.group(1)
                                date_str = match.group(2)
                                parsed_date_obj = datetime.strptime(date_str, '%d %b %Y').date()
                                self.stdout.write(self.style.SUCCESS(f"✅ Parsed Time Block -> {parsed_time_block}"))
                                self.stdout.write(self.style.SUCCESS(f"✅ Parsed Date -> {parsed_date_obj}"))
                                api_status = "DataCaptured"
                            else:
                                self.stderr.write(self.style.ERROR("Could not find time block and date in the text."))
                                api_status = "ParsingFailed"
                        except Exception as e:
                            self.stderr.write(self.style.ERROR(f"Error parsing text: {e}"))
                            api_status = "ParsingFailed"
                        
                        if api_status == "DataCaptured":
                            timestamp = run_start_time.strftime("%Y-%m-%d_%H-%M-%S")
                            screenshot_filename = f"vidyutpravah_{timestamp}.png"
                            screenshot_path = os.path.join(SCREENSHOT_DIR, screenshot_filename)
                            page.screenshot(path=screenshot_path)
                            self.stdout.write(self.style.SUCCESS(f"🖼️  Screenshot saved to: {screenshot_path}"))

                        browser.close()

                except PlaywrightTimeoutError:
                    self.stderr.write(self.style.ERROR(f"❌ Error: The operation timed out. The website might be down or very slow."))
                    api_status = "TimeoutError"
                except Exception as e:
                    self.stderr.write(self.style.ERROR(f"❌ An unexpected error occurred during capture: {e}."))
                    api_status = "ScrapingFailed"
                
                # --- Block 2: Push Status and Data to API ---
                try:
                    params = {'status': api_status}

                    if api_status == "DataCaptured":
                        self.stdout.write(self.style.HTTP_INFO("\n🧹 Cleaning data for API..."))
                        
                        clean_current = current_text.replace(",", "").replace(" MW", "").strip()
                        clean_yesterday = yesterday_text.replace(",", "").replace(" MW", "").strip()
                        formatted_date = parsed_date_obj.strftime('%Y-%m-%d')
                        formatted_time = parsed_time_block.replace(" ", "")

                        params['date'] = formatted_date
                        params['time'] = formatted_time
                        params['current'] = clean_current
                        params['yesterday'] = clean_yesterday
                        
                        self.stdout.write(f"   - Date: {params['date']}")
                        self.stdout.write(f"   - Time: {params['time']}")
                        self.stdout.write(f"   - Current: {params['current']}")
                        self.stdout.write(f"   - Yesterday: {params['yesterday']}")

                    # --- ADDED FOR VERIFICATION ---
                    # This builds the URL with all parameters for printing, just as you requested.
                    final_api_url = f"{API_ENDPOINT}?{urlencode(params)}"
                    self.stdout.write(self.style.HTTP_INFO(f"\n🚀 Pushing data to API: {final_api_url}"))
                    # ------------------------------

                    # Make the GET request.
                    response = requests.get(API_ENDPOINT, params=params, timeout=10)

                    if response.status_code == 200:
                        self.stdout.write(self.style.SUCCESS(f"✅ API call successful (Status: {response.status_code})."))
                        self.stdout.write(f"   - API Response: {response.text}")
                    else:
                        self.stderr.write(self.style.ERROR(f"❌ API call failed with status code: {response.status_code}"))
                        self.stderr.write(f"   - API Response: {response.text}")

                except requests.exceptions.RequestException as e:
                    self.stderr.write(self.style.ERROR(f"❌ An error occurred during the API call: {e}"))

                # --- Block 3: Data Saving to Database ---
                if api_status == "DataCaptured":
                    # ... (Database saving block remains unchanged) ...
                    try:
                        with transaction.atomic():
                            DemandData.objects.create(  
                                current_demand=current_text,
                                yesterday_demand=yesterday_text,
                                time_block=parsed_time_block,
                                date=parsed_date_obj
                            )
                            self.stdout.write(self.style.SUCCESS("💾 Data saved to database successfully."))
                    except Exception as e:
                        self.stderr.write(self.style.ERROR(f"❌ An unexpected error occurred during database save: {e}."))

                end_time = time.monotonic()
                duration = end_time - start_time
                self.stdout.write(self.style.SUCCESS(f"\n⏱️  Capture process finished in {duration:.2f} seconds."))
                
                # --- Countdown Timer ---
                # ... (Countdown timer remains unchanged) ...
                self.stdout.write(self.style.HTTP_INFO("\n--- Process complete. ---"))
                for i in range(WAIT_TIME_SECONDS, 0, -1):
                    minutes, seconds = divmod(i, 60)
                    print(f"Next capture in: {minutes:02d} minutes and {seconds:02d} seconds...   ", end='\r')
                    time.sleep(1)
                print("\n") 

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\n\n🛑 Script stopped by user. Exiting..."))