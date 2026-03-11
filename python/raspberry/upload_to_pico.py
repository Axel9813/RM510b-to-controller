"""
Upload Pico firmware to the DJI RC via ADB.

Pushes files to the app's external storage on the RC, then restarts the
Flutter app. On startup, the app auto-detects pending firmware files and
uploads them to the Pico via USB CDC raw REPL.

Usage:
    python upload_to_pico.py              # upload main.py + config.json
    python upload_to_pico.py main.py      # upload specific file(s)
    python upload_to_pico.py calibrate.py # upload calibration script as main.py

Requirements:
    - ADB accessible (either in PATH or bundled at ../server/adb/adb.exe)
    - DJI RC connected via USB or ADB over WiFi
    - Flutter app installed on the RC
"""

import os
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_ADB = os.path.join(SCRIPT_DIR, "..", "server", "adb", "adb.exe")
RC_FIRMWARE_DIR = "/sdcard/Android/data/com.dji.rc_to_controller/files/pico_firmware"

DEFAULT_FILES = ["main.py", "config.json"]


def find_adb():
    """Find ADB executable — bundled or in PATH."""
    if os.path.isfile(BUNDLED_ADB):
        return BUNDLED_ADB
    # Try PATH
    try:
        subprocess.run(["adb", "version"], capture_output=True, check=True)
        return "adb"
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None


def run_adb(adb, *args):
    """Run an ADB command, return (success, stdout)."""
    cmd = [adb] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"  ADB error: {result.stderr.strip()}")
        return False, result.stderr
    return True, result.stdout


def main():
    adb = find_adb()
    if not adb:
        print("ERROR: ADB not found. Install Android SDK or check ../server/adb/")
        sys.exit(1)
    print(f"Using ADB: {adb}")

    # Determine which files to upload
    if len(sys.argv) > 1:
        files = sys.argv[1:]
    else:
        files = DEFAULT_FILES

    # Resolve file paths and verify they exist
    upload_files = []
    for f in files:
        path = os.path.join(SCRIPT_DIR, f) if not os.path.isabs(f) else f
        if not os.path.isfile(path):
            print(f"ERROR: File not found: {path}")
            sys.exit(1)
        # If uploading calibrate.py, rename to main.py on the Pico
        remote_name = os.path.basename(f)
        if remote_name == "calibrate.py":
            remote_name = "main.py"
            print(f"  Note: {f} will be uploaded as main.py on the Pico")
        upload_files.append((path, remote_name))

    # Check ADB connection
    ok, out = run_adb(adb, "devices")
    if not ok:
        print("ERROR: ADB not responding")
        sys.exit(1)
    devices = [l for l in out.strip().split('\n')[1:] if l.strip() and 'device' in l]
    if not devices:
        print("ERROR: No ADB devices connected")
        sys.exit(1)
    print(f"ADB device: {devices[0].split()[0]}")

    # Create firmware directory on RC
    run_adb(adb, "shell", "mkdir", "-p", RC_FIRMWARE_DIR)

    # Push files
    for local_path, remote_name in upload_files:
        remote_path = f"{RC_FIRMWARE_DIR}/{remote_name}"
        print(f"Pushing {os.path.basename(local_path)} -> {remote_path}")
        ok, _ = run_adb(adb, "push", local_path, remote_path)
        if not ok:
            print(f"ERROR: Failed to push {local_path}")
            sys.exit(1)

    # Restart the Flutter app — it auto-detects pending firmware on startup
    print("Restarting Flutter app (firmware uploaded on Pico reader start)...")
    run_adb(adb, "shell", "am", "force-stop", "com.dji.rc_to_controller")
    time.sleep(1)
    ok, _ = run_adb(adb, "shell", "am", "start",
                     "-n", "com.dji.rc_to_controller/.MainActivity")
    if not ok:
        print("ERROR: Failed to start app")
        sys.exit(1)

    print()
    print("App restarted. It will automatically:")
    print("  1. Detect pending firmware files")
    print("  2. Upload them to the Pico via raw REPL")
    print("  3. Soft-reboot the Pico")
    print("  4. Start reading frames")
    print()
    print("Check Android logcat for progress:")
    print(f"  {adb} logcat -s PicoPlugin PicoUsbReader")


if __name__ == "__main__":
    main()
