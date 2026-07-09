# LS6-Treadmill-Monitor

Script connects to a Citysports LS6 treadmill via Bluetooth (BLE) and displays
original metrics (speed, time, distance, etc.) in real-time in the terminal,
as well as calculates several additional ones (calorie burn, elevation gain, etc.).
Does not interfere with the original remote control.

![Screenshot](img.png)

## Requirements

- Python 3
- [bleak](https://github.com/hbldh/bleak) -- BLE library
- Bluetooth enabled

## Installation and Usage

```bash
python3 -m venv .venv           # create virtual environment
source .venv/bin/activate       # activate
pip install bleak               # install dependencies
python3 ./treadmill_monitor.py  # run
```

1. Enter your weight
2. Enter the treadmill incline angle
3. Wait for automatic BLE device connection and metric display

When done, exit the venv:
```bash
deactivate
```

## How Calories Are Calculated

Calories are computed using the ACSM metabolic equations, which account for both
**speed** and **treadmill incline**:

- Walking (≤ 6 km/h):
  `VO₂ = 0.1 × S + 1.8 × S × G + 3.5`
- Running (≥ 6.1 km/h):
  `VO₂ = 0.2 × S + 0.9 × S × G + 3.5`

Where:
- `S` = speed in m/min (km/h × 1000 / 60)
- `G` = grade = tan(incline angle)
- `MET = VO₂ / 3.5`

Calories: `(MET - 1) * weight(kg) * time(h)`

## TODO

- [x] **Calculate elevation gain based on entered incline angle**
- [x] **Calculate calories taking incline into account**
- [x] **Write last metrics to a file after disconnecting from the treadmill**
- [x] **Persistent settings — save and restore weight & incline across sessions**
- [x] **Live MET gauge — real-time MET value in display**
- [x] **Connection animation — spinner during BLE scan and connection**
- [ ] **Convert kcal to estimated fat grams lost**
- [ ] **Calculate avg speed and avg MET for last metrics**

## Acknowledgements

For reverse-engineering the Bluetooth protocol of Citysports treadmills in the [FitnessMachine](https://github.com/hughesjs/FitnessMachine) project, thanks to [hughesjs](https://github.com/hughesjs)

## License

[WTFPL](http://www.wtfpl.net/) -- Do What The Fuck You Want To Public License.
