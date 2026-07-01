#!/usr/bin/env python3
"""
Citysports LS6 Treadmill Monitor

Connects to a BLE treadmill over Bluetooth and streams speed, distance,
elapsed time, and estimated calories in real time.

Calories are computed using MET values for walking on flat ground:
MET × weight(kg) × time(hours)

How to launch: 
python3 -m venv .venv  # create venv
pip3 install bleak
source .venv/bin/activate
python3 ./treadmill_monitor.py
enter your weight
enter treadmill inclination in degrees
enjoy!
deactivate  # deactivate venv



"""

import asyncio
import math
import struct
import sys

from bleak import BleakScanner, BleakClient

# BLE UUIDs (128-bit full form)
FITNESS_MACHINE_SERVICE_UUID = "00001826-0000-1000-8000-00805f9b34fb"
TREADMILL_DATA_CHAR_UUID = "00002acd-0000-1000-8000-00805f9b34fb"
FITNESS_MACHINE_CONTROL_POINT_UUID = "00002ad9-0000-1000-8000-00805f9b34fb"
SUPPORTED_SPEEDS_CHAR_UUID = "00002ad4-0000-1000-8000-00805f9b34fb"

REQUEST_CONTROL_OPCODE = bytes([0x00])

DEFAULT_WEIGHT_KG = 92.0
DEFAULT_INCLINATION_DEGREE = 2.3880155


def parse_treadmill_data(data: bytes) -> dict:
    """
    Parse with fixed offsets
    [0:2]   flags              uint16 LE
    [2:4]   speed              uint16 LE / 100  => km/h
    [4:6]   distance           uint16 LE / 1000 => km
    [13:15] elapsed time       uint16 LE        => seconds
    """
    if len(data) < 15:
        return {}

    speed_kmh = struct.unpack_from("<H", data, 2)[0] / 100.0
    distance_km = struct.unpack_from("<H", data, 4)[0] / 1000.0
    time_seconds = struct.unpack_from("<H", data, 13)[0]

    return {
        "speed_kmh": speed_kmh,
        "distance_km": distance_km,
        "time_seconds": time_seconds,
    }


def kcal_per_second(speed_kmh: float, weight_kg: float) -> float:
    """
    MET-based calorie burn rate (kcal/s) for walking on flat ground.
    kcal = MET × weight(kg) × time(hours)
    """
    if speed_kmh <= 0:
        return 0.0
    if speed_kmh < 3.2:
        met = 2.5
    elif speed_kmh < 4.0:
        met = 3.0
    elif speed_kmh < 5.6:
        met = 3.5
    else:
        met = 4.0
    return (met - 1.0) * weight_kg / 3600.0


def fmt_time(s: int) -> str:
    """Format seconds as HH:MM:SS."""
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_weight() -> float:
    """Ask the user for their weight, default to 92 kg."""
    raw = input("Enter your weight in kg (default 92): ").strip()
    if not raw:
        return DEFAULT_WEIGHT_KG
    try:
        w = float(raw)
        if w <= 0 or w > 500:
            print(f"  Weight {w} kg seems off; using {DEFAULT_WEIGHT_KG} kg.")
            return DEFAULT_WEIGHT_KG
        return w
    except ValueError:
        print(f"  Could not parse '{raw}'; using {DEFAULT_WEIGHT_KG} kg.")
        return DEFAULT_WEIGHT_KG

def parse_inclination() -> float:
    raw = input(f"Enter treadmill inclination in degrees (default {DEFAULT_INCLINATION_DEGREE}): ").strip()
    if not raw:
        return DEFAULT_INCLINATION_DEGREE
    try:
        d = float(raw)
        if d < 0 or d > 20:
            print(f"  Inclination {d}° seems off; using default value {DEFAULT_INCLINATION_DEGREE}°.")
            return DEFAULT_INCLINATION_DEGREE
        return d
    except ValueError:
        print(f"  Could not parse '{raw}'; using default value {DEFAULT_INCLINATION_DEGREE}°.")
        return DEFAULT_INCLINATION_DEGREE

async def main():
    weight_kg = parse_weight()
    inclination_deg = parse_inclination()
    print()

    print("Scanning for BLE treadmills (Fitness Machine Service 0x1826) …")
    print("Make sure your treadmill is powered on.\n")

    devices = await BleakScanner.discover(return_adv=True, timeout=10.0)

    treadmill_devices = []
    for device, adv_data in devices.values():
        uuids = adv_data.service_uuids or []
        for u in uuids:
            if FITNESS_MACHINE_SERVICE_UUID.lower() in u.lower():
                treadmill_devices.append((device, adv_data))
                break

    if not treadmill_devices:
        print("No treadmill found advertising the Fitness Machine Service.")
        print("Try power-cycling your treadmill and running the script again.")
        return

    print("Found:")
    for i, (device, _) in enumerate(treadmill_devices):
        name = device.name or "Unknown"
        print(f"  [{i}]  {name}  ({device.address})")

    if len(treadmill_devices) == 1:
        choice = 0
    else:
        try:
            choice = int(input("\nChoose device number: "))
        except (ValueError, IndexError):
            print("Invalid choice.")
            return

    device = treadmill_devices[choice][0]

    # ── state ──────────────────────────────────────────────
    cumulative_kcal = 0.0
    prev_time_s = 0
    last_display = None
    disconnected_printed = False
    disconnect_event = asyncio.Event()

    def freeze_line():
        (speed, dist, now_s, kcal, elev) = last_display
        print(
            f"\r  Speed: {speed:5.1f} km/h  |  "
            f"Distance: {dist:6.2f} km  |  "
            f"Time: {fmt_time(now_s)}  |  "
            f"Calories: {kcal:5.0f} kcal  |  "
            f"Elevation: {elev:5.0f} m   [OFF]",
            end="",
            flush=True,
        )

    def notification_handler(sender, data: bytes):
        nonlocal cumulative_kcal, prev_time_s, last_display, disconnected_printed

        parsed = parse_treadmill_data(data)
        if not parsed:
            return

        speed = parsed["speed_kmh"]
        dist = parsed["distance_km"]
        now_s = parsed["time_seconds"]

        if speed == 0.0 and dist == 0.0 and now_s == 0:
            if last_display is not None:
                if not disconnected_printed:
                    print("\nTreadmill disconnected — showing last readings:")
                    disconnected_printed = True
                freeze_line()
            return

        disconnected_printed = False

        if now_s > prev_time_s:
            dt = now_s - prev_time_s
            cumulative_kcal += kcal_per_second(speed, weight_kg) * dt
            prev_time_s = now_s

        elevation_m = dist * 1000 * math.sin(math.radians(inclination_deg))
        last_display = (speed, dist, now_s, cumulative_kcal, elevation_m)

        print(
            f"\r  Speed: {speed:5.1f} km/h  |  "
            f"Distance: {dist:6.2f} km  |  "
            f"Time: {fmt_time(now_s)}  |  "
            f"Calories: {cumulative_kcal:5.0f} kcal  |  "
            f"Elevation: {elevation_m:5.0f} m  ",
            end="",
            flush=True,
        )

    print(f"\nConnecting to {device.name or device.address} …")
    client = BleakClient(device, disconnected_callback=lambda c: disconnect_event.set())

    try:
        await client.connect()
        print("Connected!")

        try:
            await client.write_gatt_char(
                FITNESS_MACHINE_CONTROL_POINT_UUID,
                REQUEST_CONTROL_OPCODE,
                response=True,
            )
            print("Requested control.")
        except Exception:
            pass

        try:
            raw = await client.read_gatt_char(SUPPORTED_SPEEDS_CHAR_UUID)
            mn = struct.unpack_from("<H", raw, 0)[0] / 100.0
            mx = struct.unpack_from("<H", raw, 2)[0] / 100.0
            inc = struct.unpack_from("<H", raw, 4)[0] / 100.0
            print(f"Supported speeds: {mn:.1f} - {mx:.1f} km/h  (increment {inc:.1f})")
        except Exception:
            pass

        await client.start_notify(TREADMILL_DATA_CHAR_UUID, notification_handler)
        print("\nReceiving data (press Ctrl+C to stop) …\n")

        await disconnect_event.wait()
        print("\nBLE connection lost.")

    except KeyboardInterrupt:
        print("\n\nStopping …")
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        if client.is_connected:
            try:
                await client.stop_notify(TREADMILL_DATA_CHAR_UUID)
            except Exception:
                pass
            await client.disconnect()
            print("Disconnected.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
