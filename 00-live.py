import subprocess
import threading
import time
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path
import pytz

# ----------------------- Configuration Section -----------------------

STREAM_LIST_FILE = "00-streamlist.txt"

LIVE_DIR = Path("00-live")
REC_DIR = Path("01-recordings")

RECORD_DURATION = 15 * 60   # 30 minutes per chunk
OVERLAP_START = 14 * 60     # start new chunk after 19 minutes for 1-min overlap

TIMEZONE = pytz.timezone("Asia/Manila")  # GMT+8
START_HOUR = 5
END_HOUR = 0  # Treat 0 as midnight (24:00)

REPORT_INTERVAL = 60  # Report every minute

# --------------------------------------------------------------------

station_status = {}  # station_name -> True/False (online/offline)
status_lock = threading.Lock()

def current_time_str():
    now = datetime.now(TIMEZONE)
    return now.strftime("%H:%M:%S")

def load_stations(filename):
    while True:
        stations = []
        try:
            with open(filename, "r", encoding="utf-8") as f:
                lines = [line.strip() for line in f if line.strip()]
            if len(lines) < 2 or len(lines) % 2 != 0:
                print(f"Error: '{filename}' not properly formatted. Retrying in 60s...")
                time.sleep(60)
                continue
            
            for i in range(0, len(lines), 2):
                name = lines[i]
                url = lines[i+1]
                stations.append((name, url))
            
            if not stations:
                print("No stations found. Retrying in 60s...")
                time.sleep(60)
                continue
            
            return stations

        except FileNotFoundError:
            print(f"Error: '{filename}' not found. Retrying in 60s...")
            time.sleep(60)
            continue
        except Exception as e:
            print(f"Error loading stations: {e}. Retrying in 60s...")
            time.sleep(60)
            continue

def within_recording_window(now):
    hour = now.hour
    return (hour >= START_HOUR) and (hour < 24 if END_HOUR == 0 else hour < END_HOUR)

def wait_until_start():
    while True:
        now = datetime.now(TIMEZONE)
        if within_recording_window(now):
            break
        if now.hour < START_HOUR:
            next_start = now.replace(hour=START_HOUR, minute=0, second=0, microsecond=0)
        else:
            next_start = (now + timedelta(days=1)).replace(hour=START_HOUR, minute=0, second=0, microsecond=0)
        wait_seconds = (next_start - now).total_seconds()
        wait_str = str(timedelta(seconds=int(wait_seconds)))
        print(f"Outside recording window. Waiting {wait_str} until {START_HOUR}:00.")
        time.sleep(wait_seconds)

def generate_filename(station_name):
    now = datetime.now(TIMEZONE)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H-%M-%S")
    safe_name = "".join(c if c not in r'<>:"/\|?*' else "_" for c in station_name)
    filename = f"[{date_str}]-[{time_str}]-{safe_name}.mp3"
    return filename

def update_station_status(station_name, is_online):
    with status_lock:
        station_status[station_name] = is_online

def record_chunk_ffmpeg(station_name, station_url, filename, duration):
    live_path = LIVE_DIR / filename
    rec_path = REC_DIR / filename

    # Using libmp3lame encoding to ensure data is written if audio is present
    ffmpeg_command = [
        'ffmpeg',
        '-y',
        '-reconnect', '1',
        '-reconnect_streamed', '1',
        '-reconnect_delay_max', '10',
        '-i', station_url,
        '-t', str(duration),
        '-acodec', 'libmp3lame',  # Re-encode to MP3
        '-f', 'mp3',              # Specify MP3 format
        str(live_path)
    ]

    subprocess.run(ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    if live_path.exists() and live_path.stat().st_size > 0:
        # Data recorded, station online
        update_station_status(station_name, True)
        try:
            shutil.move(str(live_path), str(rec_path))
        except Exception as e:
            print(f"[{station_name}]: Error moving file: {e}")
    else:
        # No data recorded, station offline
        update_station_status(station_name, False)
        if live_path.exists():
            os.remove(live_path)



            

def record_station(station_name, station_url):
    update_station_status(station_name, False)
    while True:
        now = datetime.now(TIMEZONE)
        if not within_recording_window(now):
            wait_until_start()
            now = datetime.now(TIMEZONE)

        filename = generate_filename(station_name)
        recorder_thread = threading.Thread(target=record_chunk_ffmpeg, args=(station_name, station_url, filename, RECORD_DURATION), daemon=True)
        recorder_thread.start()

        time.sleep(OVERLAP_START)

def print_status_report():
    with status_lock:
        total = len(station_status)
        online_names = [name for name, online in station_status.items() if online]
        offline_names = [name for name, online in station_status.items() if not online]

        online_count = len(online_names)
        offline_count = len(offline_names)

        print("===")
        print(f"Online Radios: {online_count}/{total}")
        for n in online_names:
            print(n)

        print()
        print(f"Offline Radios: {offline_count}/{total}")
        for n in offline_names:
            print(n)

def reporting_loop():
    while True:
        print_status_report()
        time.sleep(REPORT_INTERVAL)

def main():
    LIVE_DIR.mkdir(exist_ok=True)
    REC_DIR.mkdir(exist_ok=True)
    
    stations = load_stations(STREAM_LIST_FILE)
    
    with status_lock:
        for station_name, _ in stations:
            station_status[station_name] = False

    # Start reporting thread
    reporter_thread = threading.Thread(target=reporting_loop, daemon=True)
    reporter_thread.start()

    # Start recording threads
    for station_name, station_url in stations:
        t = threading.Thread(target=record_station, args=(station_name, station_url), daemon=True)
        t.start()
        print(f"[{station_name}]: Recording thread started.")

    while True:
        time.sleep(3600)

if __name__ == "__main__":
    main()
