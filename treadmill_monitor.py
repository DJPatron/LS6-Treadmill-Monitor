#!/usr/bin/env python3
"""Citysports LS6 Treadmill Monitor — BLE real-time metrics."""

import asyncio
import json
import math
import os
import struct
from datetime import datetime
from bleak import BleakScanner, BleakClient

FITNESS_MACHINE_SERVICE_UUID = "00001826-0000-1000-8000-00805f9b34fb"
TREADMILL_DATA_CHAR_UUID = "00002acd-0000-1000-8000-00805f9b34fb"
FITNESS_MACHINE_CONTROL_POINT_UUID = "00002ad9-0000-1000-8000-00805f9b34fb"
SUPPORTED_SPEEDS_CHAR_UUID = "00002ad4-0000-1000-8000-00805f9b34fb"
REQUEST_CONTROL_OPCODE = bytes([0x00])
SETTINGS_FILE = "settings.json"
DEFAULT_WEIGHT_KG = 91.0
DEFAULT_INCLINATION_DEG = 2.3
SPINNER_CHARS = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def load_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {"weight_kg": DEFAULT_WEIGHT_KG, "inclination_deg": DEFAULT_INCLINATION_DEG}
    try:
        with open(SETTINGS_FILE, "r") as f:
            data = json.load(f)
        return {
            "weight_kg": float(data.get("weight_kg", DEFAULT_WEIGHT_KG)),
            "inclination_deg": float(data.get("inclination_deg", DEFAULT_INCLINATION_DEG)),
        }
    except (json.JSONDecodeError, ValueError, OSError):
        return {"weight_kg": DEFAULT_WEIGHT_KG, "inclination_deg": DEFAULT_INCLINATION_DEG}


def save_settings(weight_kg, inclination_deg):
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({"weight_kg": weight_kg, "inclination_deg": inclination_deg}, f)
    except OSError:
        pass


def parse_treadmill_data(data: bytes) -> dict:
    if len(data) < 15:
        return {}
    return {
        "speed_kmh": struct.unpack_from("<H", data, 2)[0] / 100.0,
        "distance_km": struct.unpack_from("<H", data, 4)[0] / 1000.0,
        "time_seconds": struct.unpack_from("<H", data, 13)[0],
    }


def compute_met(speed_kmh: float, inclination_deg: float) -> float:
    if speed_kmh <= 0:
        return 1.0
    speed_m_min = speed_kmh * 1000.0 / 60.0
    grade = math.tan(math.radians(inclination_deg))
    if speed_kmh <= 6.0:
        vo2 = 0.1 * speed_m_min + 1.8 * speed_m_min * grade + 3.5
    else:
        vo2 = 0.2 * speed_m_min + 0.9 * speed_m_min * grade + 3.5
    return vo2 / 3.5


def kcal_per_second(speed_kmh: float, weight_kg: float, inclination_deg: float) -> float:
    met = compute_met(speed_kmh, inclination_deg)
    return (met - 1.0) * weight_kg / 3600.0


def fmt_time(s: int) -> str:
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def display_line(speed, dist, time_s, kcal, elev, met, suffix=" ", max_speed=None, max_met=None) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if max_speed is not None:
        speed_part = f"Speed max: {max_speed:5.1f} km/h  |  "
    else:
        speed_part = f"Speed: {speed:5.1f} km/h  |  "
    if max_met is not None:
        met_part = f"MET max: {max_met:4.1f}  |  "
    else:
        met_part = f"MET: {met:4.1f}  |  "
    return (
        f"{now}  {speed_part}"
        f"Distance: {dist:6.2f} km  |  "
        f"Time: {fmt_time(time_s)}  |  "
        f"Calories: {kcal:5.0f} kcal  |  "
        f"{met_part}"
        f"Elevation: {elev:5.0f} m{suffix}"
    )


def ask_float(prompt, default, min_val, max_val, unit=""):
    raw = input(f"{prompt} (default {default}{unit}): ").strip()
    if not raw:
        return default
    try:
        val = float(raw)
        if min_val <= val <= max_val:
            return val
        print(f"  {val}{unit} seems off; using {default}{unit}.")
        return default
    except ValueError:
        print(f"  Could not parse '{raw}'; using {default}{unit}.")
        return default


async def spin_animation(message: str, done: asyncio.Event):
    i = 0
    while not done.is_set():
        print(f"\r{message} {SPINNER_CHARS[i % len(SPINNER_CHARS)]}", end="", flush=True)
        i += 1
        await asyncio.sleep(0.1)


async def discover_treadmill():
    done = asyncio.Event()
    spinner = asyncio.create_task(spin_animation("Scanning for treadmills", done))
    try:
        devices = await BleakScanner.discover(return_adv=True, timeout=10.0)
    finally:
        done.set()
        await spinner
        print("\r" + " " * 60, end="\r")
    treadmills = [
        (device, adv)
        for device, adv in devices.values()
        if any(
            FITNESS_MACHINE_SERVICE_UUID.lower() in (u or "").lower()
            for u in (adv.service_uuids or [])
        )
    ]

    if not treadmills:
        print("No treadmill found. Power-cycle it and try again.")
        return None

    print("Found:")
    for i, (device, _) in enumerate(treadmills):
        print(f"  [{i}]  {device.name or 'Unknown'}  ({device.address})")

    if len(treadmills) == 1:
        return treadmills[0][0]

    try:
        choice = int(input("\nChoose device number: "))
        return treadmills[choice][0]
    except (ValueError, IndexError):
        print("Invalid choice.")
        return None


async def run_monitor(device, weight_kg, inclination_deg):
    cumulative_kcal = 0.0
    prev_time_s = 0
    max_speed = 0.0
    max_met = 1.0
    last_display = None
    disconnected_printed = False
    training_saved = False
    disconnect_event = asyncio.Event()

    def save_training():
        save_settings(weight_kg, inclination_deg)
        line = display_line(*last_display, max_speed=max_speed, max_met=max_met, suffix="\n")
        with open("trainings.txt", "a") as f:
            f.write(line)
        print("\nLast metrics saved to trainings.txt")

    def try_save_training():
        nonlocal training_saved
        if not training_saved and last_display is not None:
            save_training()
            training_saved = True

    def notification_handler(sender, data: bytes):
        nonlocal cumulative_kcal, prev_time_s, max_speed, max_met, last_display, disconnected_printed, training_saved

        parsed = parse_treadmill_data(data)
        if not parsed:
            return

        speed, dist, now_s = parsed["speed_kmh"], parsed["distance_km"], parsed["time_seconds"]
        if speed > 0:
            max_speed = max(max_speed, speed)

        if speed == 0.0 and dist == 0.0 and now_s == 0:
            if last_display is not None:
                if not disconnected_printed:
                    print("\nTreadmill stopped or disconnected.")
                    disconnected_printed = True
                    try_save_training()
                    cumulative_kcal = 0.0
                    prev_time_s = 0
                    max_speed = 0.0
                    max_met = 1.0
                    training_saved = False
            return

        disconnected_printed = False

        if now_s < prev_time_s:
            try_save_training()
            cumulative_kcal = 0.0
            prev_time_s = 0
            max_speed = 0.0
            max_met = 1.0
            return

        if now_s > prev_time_s:
            cumulative_kcal += kcal_per_second(speed, weight_kg, inclination_deg) * (now_s - prev_time_s)
            prev_time_s = now_s

        elevation_m = dist * 1000 * math.sin(math.radians(inclination_deg))
        current_met = compute_met(speed, inclination_deg)
        if speed > 0:
            max_met = max(max_met, current_met)
        last_display = (speed, dist, now_s, cumulative_kcal, elevation_m, current_met)

        print("\r" + display_line(*last_display, suffix="  "), end="", flush=True)

    print(f"Connecting to {device.name or device.address} …")
    client = BleakClient(device, disconnected_callback=lambda c: disconnect_event.set())

    try:
        done = asyncio.Event()
        spinner = asyncio.create_task(spin_animation("Connecting", done))
        try:
            await client.connect()
        finally:
            done.set()
            await spinner
            print("\r" + " " * 60, end="\r")
        print("Connected!")

        try:
            await client.write_gatt_char(
                FITNESS_MACHINE_CONTROL_POINT_UUID, REQUEST_CONTROL_OPCODE, response=True
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
        try_save_training()

    except (KeyboardInterrupt, asyncio.CancelledError):
        print("\n\nStopping …")
        try_save_training()
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


async def main():
    settings = load_settings()
    has_saved = os.path.exists(SETTINGS_FILE)
    weight_kg = ask_float("Enter your weight in kg", settings["weight_kg"], 0, 500, " kg") if not has_saved else settings["weight_kg"]
    inclination_deg = ask_float(
        "Enter treadmill inclination in degrees", settings["inclination_deg"], 0, 20, "°"
    ) if not has_saved else settings["inclination_deg"]
    if has_saved:
        print(f"Weight: {weight_kg} kg  |  Inclination: {inclination_deg}°  (from settings.json)")
    print()

    device = await discover_treadmill()
    if device is None:
        return

    await run_monitor(device, weight_kg, inclination_deg)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
