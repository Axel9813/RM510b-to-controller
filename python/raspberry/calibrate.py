"""
Pico GPIO Calibration Script — discovers what's wired to which pin.

Upload this to the Pico (replaces main.py temporarily) or run via
the OTA updater. It monitors ALL usable GPIO pins and reports changes
over USB CDC as human-readable text AND as an extended bitmask frame.

Usage:
  1. Upload to Pico as main.py (or run via raw REPL)
  2. Press each button one at a time
  3. The script prints which GPIO pin changed state
  4. ADC readings for pins 26, 27, 28 are printed periodically

LED blinks fast (4 Hz) to indicate calibration mode.

Extended frame format (for machine parsing):
  [0xBB] [gpio_0_7] [gpio_8_15] [gpio_16_22] [adc26_lo] [adc26_hi]
         [adc27_lo] [adc27_hi] [adc28_lo] [adc28_hi]
  Total: 10 bytes per frame, sent at 20 Hz
"""

import sys
import time
from machine import Pin, ADC

_led = Pin(25, Pin.OUT)
_led.on()

_write = getattr(sys.stdout, 'buffer', sys.stdout).write

# All usable GPIO pins for digital input (excluding 23=SMPS, 24=VBUS, 25=LED)
DIGITAL_PINS = list(range(0, 23)) + [26, 27, 28]

# ADC-capable pins
ADC_PINS = [26, 27, 28]

SYNC_BYTE = 0xBB  # different from normal 0xAA to distinguish calibration mode


def main():
    print("=== PICO GPIO CALIBRATION ===")
    print(f"Monitoring {len(DIGITAL_PINS)} digital pins + {len(ADC_PINS)} ADC pins")
    print("Press buttons one at a time. Changes will be reported.")
    print()

    # Set up all digital pins as INPUT with internal PULL_UP
    # (so unconnected pins read HIGH, connected-to-GND buttons read LOW)
    pins = {}
    for gpio in DIGITAL_PINS:
        try:
            pins[gpio] = Pin(gpio, Pin.IN, Pin.PULL_UP)
        except Exception as e:
            print(f"  GPIO {gpio}: SKIP ({e})")

    # Set up ADC
    adcs = {}
    for gpio in ADC_PINS:
        try:
            adcs[gpio] = ADC(Pin(gpio))
        except Exception:
            pass

    # Read initial state
    prev_state = {}
    for gpio, pin in pins.items():
        prev_state[gpio] = pin.value()

    prev_adc = {}
    for gpio, adc in adcs.items():
        prev_adc[gpio] = adc.read_u16()

    # Print initial state summary
    low_pins = [g for g, v in prev_state.items() if v == 0]
    high_pins = [g for g, v in prev_state.items() if v == 1]
    print(f"Initially LOW (pulled to GND / button pressed): {low_pins}")
    print(f"Initially HIGH (pull-up / released): {sorted(high_pins)}")
    print()
    for gpio in ADC_PINS:
        if gpio in adcs:
            val = prev_adc[gpio]
            voltage = val * 3.3 / 65535
            print(f"  ADC GPIO {gpio}: raw={val} ({voltage:.2f}V)")
    print()
    print("--- Monitoring for changes (press buttons now) ---")
    print()

    led_time = time.ticks_ms()
    adc_report_time = time.ticks_ms()

    while True:
        now = time.ticks_ms()

        # Check digital pins for changes
        for gpio, pin in pins.items():
            val = pin.value()
            if val != prev_state[gpio]:
                state_str = "LOW (PRESSED)" if val == 0 else "HIGH (released)"
                print(f"  >>> GPIO {gpio:2d} -> {state_str}")
                prev_state[gpio] = val

        # Report ADC periodically (every 200ms for responsive joystick tracking)
        if time.ticks_diff(now, adc_report_time) >= 200:
            for gpio, adc in adcs.items():
                val = adc.read_u16()
                diff = abs(val - prev_adc[gpio])
                if diff > 200:  # report on moderate changes
                    voltage = val * 3.3 / 65535
                    print(f"  ADC GPIO {gpio}: raw={val} ({voltage:.2f}V) delta={diff}")
                prev_adc[gpio] = val
            adc_report_time = now

        # Fast LED blink (4 Hz) to show calibration mode
        if time.ticks_diff(now, led_time) >= 125:
            _led.toggle()
            led_time = now

        time.sleep_ms(10)


try:
    main()
except Exception as e:
    print(f"CALIBRATE ERROR: {e}")
    time.sleep(5)
    import machine
    machine.soft_reset()
