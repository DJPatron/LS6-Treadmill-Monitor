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

The current formula uses MET values for walking on **flat surfaces**:

| Speed        | MET |
|--------------|-----|
| < 3.2 km/h   | 2.5 |
| 3.2-4.0 km/h | 3.0 |
| 4.0-5.6 km/h | 3.5 |
| > 5.6 km/h   | 4.0 |

Calories: `(MET - 1) * weight(kg) * time(h)`

## TODO

- [x] **Calculate elevation gain based on entered incline angle**
- [ ] **Calculate calories taking incline into account**
- [x] **Write last metrics to a file after disconnecting from the treadmill**

## Acknowledgements

For reverse-engineering the Bluetooth protocol of Citysports treadmills in the [FitnessMachine](https://github.com/hughesjs/FitnessMachine) project, thanks to [hughesjs](https://github.com/hughesjs)

## License

[WTFPL](http://www.wtfpl.net/) -- Do What The Fuck You Want To Public License.
