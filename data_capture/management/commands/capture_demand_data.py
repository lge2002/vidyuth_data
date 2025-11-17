# data_capture/management/commands/capture_demand_data.py

import time
import os
import re
import requests
from urllib.parse import urlencode
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand
from django.db import transaction
# new imports for robust DB handling
from django import db as django_db
from django.db import connection
from django.db.utils import OperationalError, DatabaseError
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from data_capture.models import DemandData

class Command(BaseCommand):
    """
    A Django management command that continuously captures power demand data, a time block,
    and a screenshot from the Vidyut PRAVAH website.
    Keeps screenshots only for today and yesterday (rotates older files out).
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
        KEEP_DAYS = 2  # keep screenshots for this many days (today and yesterday -> 2)
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

                        # --- Screenshot saving & rotation logic ---
                        if api_status == "DataCaptured":
                            try:
                                # Use date-only filename so each date has just one screenshot file.
                                # This prevents files piling up with timestamps.
                                screenshot_date = run_start_time.date()  # date when script runs
                                screenshot_filename = f"vidyutpravah_{screenshot_date.strftime('%Y-%m-%d')}.png"
                                screenshot_path = os.path.join(SCREENSHOT_DIR, screenshot_filename)

                                # Take screenshot (overwrite existing file for that date if present)
                                page.screenshot(path=screenshot_path)
                                self.stdout.write(self.style.SUCCESS(f"🖼️  Screenshot saved to: {screenshot_path}"))

                                # Cleanup older screenshots: keep only files for the last KEEP_DAYS days
                                keep_dates = set()
                                for d in range(KEEP_DAYS):
                                    dt = (run_start_time.date() - timedelta(days=d))
                                    keep_dates.add(dt.strftime('%Y-%m-%d'))

                                allowed_filenames = {f"vidyutpravah_{d}.png" for d in keep_dates}

                                # remove any vidyutpravah_*.png not in allowed_filenames
                                for fname in os.listdir(SCREENSHOT_DIR):
                                    if not fname.startswith("vidyutpravah_") or not fname.lower().endswith(".png"):
                                        continue
                                    if fname not in allowed_filenames:
                                        fpath = os.path.join(SCREENSHOT_DIR, fname)
                                        try:
                                            os.remove(fpath)
                                            self.stdout.write(self.style.WARNING(f"🗑️  Removed old screenshot: {fpath}"))
                                        except Exception as e:
                                            self.stderr.write(self.style.ERROR(f"Failed to remove old screenshot {fpath}: {e}"))

                            except PlaywrightTimeoutError:
                                self.stderr.write(self.style.ERROR("❌ Screenshot timed out."))
                                api_status = "TimeoutError"
                            except Exception as e:
                                self.stderr.write(self.style.ERROR(f"❌ Failed to capture/save screenshot: {e}"))
                                # We don't change api_status here; DB/save can still proceed.

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
                    final_api_url = f"{API_ENDPOINT}?{urlencode(params)}"
                    self.stdout.write(self.style.HTTP_INFO(f"\n🚀 Pushing data to API: {final_api_url}"))
                    # ------------------------------

                    response = requests.get(API_ENDPOINT, params=params, timeout=10)

                    if response.status_code == 200:
                        self.stdout.write(self.style.SUCCESS(f"✅ API call successful (Status: {response.status_code})."))
                        self.stdout.write(f"   - API Response: {response.text}")
                    else:
                        self.stderr.write(self.style.ERROR(f"❌ API call failed with status code: {response.status_code}"))
                        self.stderr.write(f"   - API Response: {response.text}")

                except requests.exceptions.RequestException as e:
                    self.stderr.write(self.style.ERROR(f"❌ An error occurred during the API call: {e}"))

                # --- Block 3: Data Saving to Database (robust) ---
                if api_status == "DataCaptured":
                    saved = False
                    max_attempts = 4
                    attempt = 0

                    # prepare values for save
                    cd = current_text
                    yd = yesterday_text
                    tb = parsed_time_block
                    pd = parsed_date_obj

                    while attempt < max_attempts and not saved:
                        attempt += 1
                        try:
                            # 1) Close old/stale connections held by Django
                            try:
                                django_db.close_old_connections()
                            except Exception:
                                # best-effort - ignore if not supported
                                pass

                            # 2) Ensure low-level connection is usable (Django helper if available)
                            try:
                                if hasattr(connection, "ensure_connection"):
                                    connection.ensure_connection()
                                else:
                                    try:
                                        connection.close()
                                    except Exception:
                                        pass
                            except Exception:
                                # fallback: close connection to force a fresh one next attempt
                                try:
                                    connection.close()
                                except Exception:
                                    pass

                            # 3) Write inside a transaction
                            with transaction.atomic():
                                DemandData.objects.create(
                                    current_demand=cd,
                                    yesterday_demand=yd,
                                    time_block=tb,
                                    date=pd
                                )

                            self.stdout.write(self.style.SUCCESS("💾 Data saved to database successfully."))
                            saved = True

                        except (OperationalError, DatabaseError) as db_err:
                            err_text = str(db_err)
                            self.stderr.write(self.style.ERROR(f"❌ Database error on attempt {attempt}/{max_attempts}: {err_text}"))

                            # close underlying connection to force fresh connection on next attempt
                            try:
                                connection.close()
                            except Exception:
                                pass

                            if attempt >= max_attempts:
                                self.stderr.write(self.style.ERROR(f"❌ Failed to save to DB after {max_attempts} attempts. Last error: {err_text}"))
                                break

                            backoff = 2 ** attempt
                            self.stdout.write(self.style.WARNING(f"⏳ Retrying DB save in {backoff} seconds... (next attempt {attempt+1}/{max_attempts})"))
                            time.sleep(backoff)
                            continue

                        except Exception as e:
                            # Non-db related exception -> log and break
                            self.stderr.write(self.style.ERROR(f"❌ An unexpected error occurred during database save: {e}"))
                            try:
                                connection.close()
                            except Exception:
                                pass
                            break

                    if not saved:
                        # optional: you can queue these records for later manual retry
                        self.stderr.write(self.style.ERROR("❌ Record was not saved to the database."))

                end_time = time.monotonic()
                duration = end_time - start_time
                self.stdout.write(self.style.SUCCESS(f"\n⏱️  Capture process finished in {duration:.2f} seconds."))

                # --- Countdown Timer ---
                self.stdout.write(self.style.HTTP_INFO("\n--- Process complete. ---"))
                for i in range(WAIT_TIME_SECONDS, 0, -1):
                    minutes, seconds = divmod(i, 60)
                    print(f"Next capture in: {minutes:02d} minutes and {seconds:02d} seconds...   ", end='\r')
                    time.sleep(1)
                print("\n")

        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\n\n🛑 Script stopped by user. Exiting..."))
