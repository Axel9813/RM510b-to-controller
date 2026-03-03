import re
import subprocess
import pyvjoy


VJOY_DEVICE_ID = 1

j = pyvjoy.VJoyDevice(VJOY_DEVICE_ID)


configured_buttons = None


def detect_dji_event_device():
    try:
        result = subprocess.run(
            ["adb", "shell", "getevent", "-lp"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        message = "ADB getevent failed."
        if stderr:
            message += f"\nADB stderr: {stderr}"
        if stdout:
            message += f"\nADB stdout: {stdout}"
        message += "\nCheck that adb is running, the device is connected, and 'adb shell getevent -lp' works."
        raise RuntimeError(message) from exc

    devices = []
    current = None
    for line in result.stdout.splitlines():
        if line.startswith("add device"):
            if current:
                devices.append(current)
            match = re.search(r"/dev/input/event\d+", line)
            current = {
                "path": match.group(0) if match else None,
                "name": "",
                "abs": {},
            }
            continue

        if current is None:
            continue

        name_match = re.search(r"name:\s*\"(.+?)\"", line)
        if name_match:
            current["name"] = name_match.group(1)
            continue

        abs_match = re.search(r"ABS_[A-Z0-9_]+", line)
        if abs_match:
            axis = abs_match.group(0)
            min_match = re.search(r"min\s+(-?\d+)", line)
            max_match = re.search(r"max\s+(-?\d+)", line)
            if min_match and max_match:
                current["abs"][axis] = {
                    "min": int(min_match.group(1)),
                    "max": int(max_match.group(1)),
                }

    if current:
        devices.append(current)

    # Heuristic: choose a device that exposes multiple axes and a reasonable name.
    def score(dev):
        name = dev.get("name", "").lower()
        axis_count = len(dev.get("abs", {}))
        name_bonus = 0
        if "rm" in name or "dji" in name or "remote" in name or "controller" in name:
            name_bonus = 5
        return axis_count + name_bonus

    devices = [d for d in devices if d.get("path")]
    if not devices:
        raise RuntimeError("No input devices found via ADB getevent -lp")

    devices.sort(key=score, reverse=True)
    return devices[0]["path"], devices[0].get("abs", {})


def scale_axis(value, axis_min, axis_max, invert=False):
    if axis_max <= axis_min:
        return 0
    scaled = int(((value - axis_min) / (axis_max - axis_min)) * 32767)
    if invert:
        scaled = 32767 - scaled
    return scaled


device_path, axis_info_map = detect_dji_event_device()

print(f"Detected device: {device_path}", flush=True)
print(f"Axis info: {axis_info_map}", flush=True)

# Test POV configuration
if hasattr(j, "set_cont_pov"):
    print(f"Device acquired. Attempting POV test...", flush=True)
    pov_working = False
    pov_errors = {}
    for pov_id in [1, 2, 3, 4]:
        try:
            j.set_cont_pov(0xFFFF, pov_id)  # 0xFFFF = centered
            print(f"✓ POV {pov_id} works!", flush=True)
            pov_working = True
            break
        except Exception as e:
            pov_errors[pov_id] = f"{type(e).__name__}"
    
    if not pov_working:
        print("\n⚠ POV not working on this device!", flush=True)
        print("Possible causes:", flush=True)
        print("  1. vJoyConf POV settings not saved properly - restart vJoyConf and try 'Reset All'", flush=True)
        print("  2. Device not properly reacquired after vJoyConf changes", flush=True)
        print("  3. vJoy driver/device mismatch - try rebooting", flush=True)
        print("\nContinuing with axes and buttons only (POV disabled)\n", flush=True)
else:
    print("WARNING: pyvjoy doesn't support POV", flush=True)

print("Starting event loop... Move sticks and press buttons to test.", flush=True)

# Запуск процесса чтения через ADB
process = subprocess.Popen(
    ["adb", "shell", "getevent", "-l", device_path],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    bufsize=1,
)

axis_map = {
    "ABS_X": pyvjoy.HID_USAGE_X,
    "ABS_Y": pyvjoy.HID_USAGE_Y,
    "ABS_Z": pyvjoy.HID_USAGE_Z,
    "ABS_RX": pyvjoy.HID_USAGE_RX,
    "ABS_RY": pyvjoy.HID_USAGE_RY,
    "ABS_RZ": pyvjoy.HID_USAGE_RZ,
    "ABS_THROTTLE": pyvjoy.HID_USAGE_SL0,
    "ABS_RUDDER": pyvjoy.HID_USAGE_SL1,
    "ABS_WHEEL": pyvjoy.HID_USAGE_SL0,
    "ABS_GAS": pyvjoy.HID_USAGE_SL0,
    "ABS_BRAKE": pyvjoy.HID_USAGE_SL1,
}

key_to_button = {}
next_button = 1
max_buttons = 128

hat_button_ids = {}
hat_button_state = {
    "up": 0,
    "down": 0,
    "left": 0,
    "right": 0,
}

hat_x = 0
hat_y = 0
pov_error_shown = False


def update_pov(x_val, y_val):
    global pov_error_shown
    if not hasattr(j, "set_cont_pov"):
        return "no_method"
    
    # Try POV IDs 1-4 (library rejects 0 and >4)
    for pov_id in [1, 2, 3, 4]:
        try:
            direction_map = {
                (0, 1): 0,
                (1, 1): 4500,
                (1, 0): 9000,
                (1, -1): 13500,
                (0, -1): 18000,
                (-1, -1): 22500,
                (-1, 0): 27000,
                (-1, 1): 31500,
            }
            
            if x_val == 0 and y_val == 0:
                j.set_cont_pov(0xFFFF, pov_id)
                return f"centered(POV{pov_id})"
            else:
                direction = direction_map.get((x_val, y_val), -1)
                j.set_cont_pov(direction, pov_id)
                return f"direction={direction}(POV{pov_id})"
        except Exception as e:
            continue
    
    if not pov_error_shown:
        pov_error_shown = True
        print(f"\nPOV: All POV IDs (1-4) failed - may not be properly configured\n", flush=True)
    return "disabled"


def set_hat_button(direction, pressed):
    global next_button
    button_id = hat_button_ids.get(direction)
    if button_id is None and pressed:
        if next_button <= max_buttons:
            button_id = next_button
            hat_button_ids[direction] = button_id
            next_button += 1
    if button_id is None:
        return
    j.set_button(button_id, 1 if pressed else 0)
    hat_button_state[direction] = 1 if pressed else 0


def update_hat_buttons(x_val, y_val):
    active = None
    if x_val == 0 and y_val == 0:
        active = None
    elif x_val != 0 and y_val != 0:
        # 4-way mode: prioritize Y on diagonals
        active = "up" if y_val > 0 else "down"
    elif y_val != 0:
        active = "up" if y_val > 0 else "down"
    else:
        active = "right" if x_val > 0 else "left"

    for direction in hat_button_state:
        pressed = direction == active
        if hat_button_state[direction] != (1 if pressed else 0):
            set_hat_button(direction, pressed)


def normalize_hat(value, axis_info):
    axis_min = axis_info.get("min", -1)
    axis_max = axis_info.get("max", 1)
    if value <= axis_min:
        return -1
    if value >= axis_max:
        return 1
    return 0


def parse_event_line(line):
    parts = line.strip().split()
    if len(parts) < 3:
        return None
    event_type = parts[0]
    code = parts[1]
    value_hex = parts[2]
    return event_type, code, value_hex


while True:
    line = process.stdout.readline()
    if not line:
        break

    parsed = parse_event_line(line)
    if not parsed:
        continue

    event_type, code, value_hex = parsed

    if event_type == "EV_ABS":
        # Convert hex to signed 32-bit integer
        value = int(value_hex, 16)
        if value > 0x7FFFFFFF:
            value -= 0x100000000

        if code in ("ABS_HAT0X", "ABS_HAT0Y"):
            axis_info = axis_info_map.get(code, {"min": -1, "max": 1})
            if code == "ABS_HAT0X":
                hat_x = normalize_hat(value, axis_info)
            else:
                hat_y = normalize_hat(value, axis_info)
            update_hat_buttons(hat_x, hat_y)
            pov_result = update_pov(hat_x, hat_y)
            # Always print POV for debugging
            print(f"POV: hat_x={hat_x}, hat_y={hat_y}, result={pov_result}", flush=True)
            continue

        if code in axis_map:
            axis_info = axis_info_map.get(code)
            if not axis_info:
                print(f"Warning: No calibration data for {code}, skipping", flush=True)
                continue
            # Invert Y axes to match standard joystick behavior
            invert = code in ("ABS_Y", "ABS_RY")
            vjoy_val = scale_axis(value, axis_info["min"], axis_info["max"], invert)
            j.set_axis(axis_map[code], vjoy_val)
            print(f"Axis {code}: raw={value}, scaled={vjoy_val}, inverted={invert}, range={axis_info}", flush=True)

    elif event_type == "EV_KEY":
        # Handle both hex values and DOWN/UP strings
        if value_hex in ("DOWN", "UP"):
            value = 1 if value_hex == "DOWN" else 0
        else:
            value = int(value_hex, 16)
        
        if code not in key_to_button and next_button <= max_buttons:
            key_to_button[code] = next_button
            next_button += 1
        button_id = key_to_button.get(code)
        if button_id:
            j.set_button(button_id, 1 if value else 0)
            print(f"Button {code} -> vJoy button {button_id}: {value}", flush=True)