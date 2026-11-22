[![tests](https://github.com/PatrickBaus/data_logger/actions/workflows/tests.yml/badge.svg)](https://github.com/PatrickBaus/data_logger/actions/workflows/tests.yml)
[![pylint](https://github.com/PatrickBaus/data_logger/actions/workflows/pylint.yml/badge.svg)](https://github.com/PatrickBaus/data_logger/actions/workflows/pylint.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/PatrickBaus/data_logger/python-coverage-comment-action-data/endpoint.json)](https://github.com/PatrickBaus/data_logger/tree/python-coverage-comment-action-data)
[![License: GPL v3](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE)
[![code style](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
# data_logger
A Python3 [asyncio](https://docs.python.org/3/library/asyncio.html) data logger for lab instruments. It reads
multimeters, thermometers, temperature controllers and humidity sensors over GPIB, Ethernet, serial ports and USB and
writes the readings to a CSV file, an MQTT broker, or both. All instruments are read in parallel, one row per round.

The logger is meant to run unattended for days or weeks: invalid readings and timeouts are logged and skipped, lost
connections are re-established automatically and errors are additionally written to `errors.log`.

The logger requires Python 3.12 or newer.

## Supported Instruments
|Instrument|`driver`|Interface|Connection parameters|
|--|--|--|--|
|HP/Keysight 3458A|`hp3458a`|GPIB (linux-gpib)|`name`, `pad`, `timeout`|
|Keysight 34470A|`ks34470a`|Ethernet (SCPI socket)|`host`, `port`, `timeout`|
|Keithley DMM6500|`dmm6500`|Ethernet (SCPI socket)|`host`, `port`, `timeout`|
|Keithley 2002|`k2002`|GPIB (linux-gpib)|`name`, `pad`, `timeout`|
|Keithley 2002 with scanner card|`k2002_scanner`|GPIB (linux-gpib)|`name`, `pad`, `timeout`, `active_channels`|
|Keithley 26xxB SMU|`k26xxb`|Ethernet (TSP socket)|`host`, `port`, `timeout`|
|Fluke 1524 thermometer|`fluke1524`|Serial/USB|`tty` or `vid`/`pid`/`serial_number`, `baudrate`, `timeout`|
|Fluke 1590 Super-Thermometer|`fluke1590`|GPIB (Prologix Ethernet)|`host`, `port`, `pad`, `timeout`|
|E+E EE07 humidity probe|`ee07`|Serial/USB|`tty` or `vid`/`pid`/`serial_number`, `baudrate`, `timeout`|
|ILX Lightwave LDT-5948|`ldt5948`|Serial/USB|`tty` or `vid`/`pid`/`serial_number`, `baudrate`, `timeout`|
|Tinkerforge Humidity Bricklet 2.0|`tinkerforge`|Ethernet (Brick Daemon)|`host`, `uid`|

All timeouts are in seconds.

## Setup
Clone the repository and install the dependencies in a virtual environment:
```bash
git clone https://github.com/PatrickBaus/data_logger.git
cd data_logger
python3 -m venv env
source env/bin/activate
pip install -r requirements.txt
```

Instruments using a GPIB card additionally need [linux-gpib](https://linux-gpib.sourceforge.io/) installed on the
host. The [Prologix](https://prologix.biz/) Ethernet adapter does not need any drivers.

## Usage
Write a configuration file (see below), then start the logger:
```bash
python3 data_logger.py --config_file config.yml
```

Stop it with `Ctrl+C`, `SIGTERM` or `SIGHUP`. The logger waits up to 3 seconds for each endpoint to write the queued
data and disconnects the instruments before it exits.

## Configuration
The configuration is a YAML file with two sections, `endpoints` and `devices`, and two optional settings:

```yaml
time_interval: 0  # Minimum time in seconds between two readings. The slowest instrument sets the pace. Default: 0
reconnect_interval: 5  # Time in seconds to wait before reconnecting after a connection error. Default: 5
endpoints:
    ...
devices:
    ...
```

### Endpoints
There are two endpoints. Each can be used at most once.

`file` appends the data to a CSV file. `{date}` in the file name is replaced by the start time of the logger. Missing
directories are created.
```yaml
endpoints:
    file: {filename: "data/my_measurement_{date}.csv", descriptor: "A short description of the setup, written to the header."}
```

`mqtt` publishes each value as a JSON message to the topic of the device. `hosts` is a single broker, a comma
separated list or a YAML list of brokers of a cluster. The port defaults to 1883. Use `null` for the `username` and
`password`, if the broker does not need authentication.
```yaml
endpoints:
    mqtt: {hosts: "broker1.example.com:1883,broker2.example.com:1883", username: "foo", password: "bar"}
```

### Devices
Each device needs a `driver`, a `uuid` and the connection parameters listed in the table above. The `uuid` identifies
the instrument in the MQTT messages, create one with `python3 -c "import uuid; print(uuid.uuid4())"`. These settings
are optional for every device:

|Setting|Description|
|--|--|
|`device_name`|A name used in the log messages. Defaults to the instrument id (`*IDN?`).|
|`column_names`|The column names of the CSV header, one per value returned by the device.|
|`initial_commands`|Commands sent once after connecting, for example to set the range or the integration time.|
|`post_read_commands`|Commands sent after a reading. See [Post-read commands](#post-read-commands).|
|`base_topic`|The MQTT topic. Devices with several values publish to sub-topics like `<base_topic>/temperature`. Required for the `mqtt` endpoint.|

### Post-read commands
A post-read command is either a plain string, which is sent after every reading, or a dict with these keys:

|Key|Description|
|--|--|
|`cmd`|The command. Required.|
|`delay`|Wait this many seconds after the start of the logger before sending the command. A number or an arithmetic expression like `"60*60*24"`, using `+ - * / // % **`.|
|`repeat`|Send the command this many times. Default: -1, which sends it after every reading.|

```yaml
post_read_commands: [
    "INIT",  # after every reading
    {cmd: "SYSTem:BEEP", delay: "60*60*24", repeat: 1},  # once, a day after the start
]
```

## Examples
### A DMM logging to a file
The minimal setup: a Keysight 34470A on the network, logged to a CSV file.
```yaml
endpoints:
    file: {filename: "data/reference_{date}.csv", descriptor: "10 V reference measured with a 34470A."}
devices:
    - {driver: ks34470a, uuid: 9a4fc6d1-6f0b-4e0a-8a59-0d3c5d4ea1a7, host: 192.168.1.10, port: 5025, timeout: 5,
       column_names: ["Voltage (V)"],
       initial_commands: [
           "SENSe:FUNCtion 'VOLTage:DC'",
           "SENSe:VOLTage:DC:RANGe 10",
           "SENSe:VOLTage:DC:NPLC 10",
       ]}
```

### Scanning 10 channels with a Keithley 2002
A K2002 with a SCAN2000 card on GPIB address 16 of the first GPIB card. The readings are transferred as binary
doubles, so the format must be set to `REAL,64`.
```yaml
devices:
    - {driver: k2002_scanner, uuid: 15d9f44c-03b4-465b-b596-4cb623d57199, name: 0, pad: 16, timeout: 100,
       active_channels: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
       base_topic: "sensors/room_011/LM399/k2002",
       initial_commands: [
           "*CLS",
           "*RST",
           "*OPC?",
           ":SENS:VOLT:DC:RANGe 20; DIG 9; NPLC 10",
           ":FORM:DATA REAL,64",  # read data as bytes instead of text
           ":FORM:ELEM READing",  # only return the reading, not the channel or a timestamp
           ":INITiate:CONTinuous OFF; :ABORt",
           ":ROUTE:SCAN:LSEL INT",  # Enable the internal scanner card
           ":INITiate:CONTinuous ON",
       ]}
```

### Serial instruments found by their USB adapter
A `tty` like `/dev/ttyUSB0` can change when the adapter is plugged in again. Use the VID, PID and serial number of the
USB adapter instead, they are looked up on every connection attempt. `lsusb` or
`python3 -m serial.tools.list_ports -v` shows them.
```yaml
devices:
    - {driver: ldt5948, uuid: c9e5e997-6db6-42ec-90ea-70052a091ea0, vid: 0x0403, pid: 0x6001, serial_number: "AC01QN76",
       baudrate: 115200, timeout: 0.5,
       column_names: ["Temperature in loop", "TEC current", "TEC voltage", "Temperature setpoint"],
       base_topic: "sensors/room_011/ldt5948"}
    - {driver: fluke1524, uuid: 803045a8-1c74-4e02-b9b7-232f3ad77be7, tty: "/dev/ttyUSB1", baudrate: 9600, timeout: 1,
       column_names: ["Temperature (PCB)", "Temperature (Room)"],
       base_topic: "sensors/room_011/fluke1524"}
```

### Room monitoring over MQTT
Humidity and temperature of a lab, published to an MQTT broker only, once a minute.
```yaml
time_interval: 60
endpoints:
    mqtt: {hosts: ["mqtt.example.com"], username: null, password: null}
devices:
    - {driver: ee07, uuid: 7ea1048c-eaad-42cf-aff9-ab69c69eb0ee, tty: "/dev/ttyACM0", baudrate: 115200, timeout: 0.5,
       base_topic: "sensors/room_011/ee07"}
    - {driver: tinkerforge, uuid: 0c5f3a4e-2a1d-4d1e-9b6f-0e8f0a7d3b21, host: "localhost", uid: "Dm6",
       base_topic: "sensors/room_012/tinkerforge"}
```

The messages look like this:
```
sensors/room_011/ee07/humidity {"timestamp": 1767323045.12, "uuid": "7ea1048c-eaad-42cf-aff9-ab69c69eb0ee", "sid": 0, "value": 41.23, "unit": "%rH"}
sensors/room_011/ee07/temperature {"timestamp": 1767323045.12, "uuid": "7ea1048c-eaad-42cf-aff9-ab69c69eb0ee", "sid": 1, "value": 22.41, "unit": "°C"}
```

A complete example with several instruments and both endpoints is in [config_example.yml](config_example.yml).

## Output
The CSV file starts with a header, all header lines begin with `#`. It contains the version of the logger, the
`descriptor`, calibration data of the instruments, if they report it, the start time and the column names. Each
following line is one round of readings, starting with the UTC timestamp:
```
# This file was generated using the Python data logger script v0.9.21.
# Check https://github.com/PatrickBaus/data_logger for the latest version.
# This file contains voltages of 10 LM399/ADR1399 references which are scanned using a K2002 and a SCAN2000 SSR card.
# K2002 Cal date=2022-11-29 00:00:00+00:00; Next Cal due=2023-11-29 00:00:00+00:00
# LDT5948 PID constants Kp=15.00; Ki=0.003; Kd=2.000
# Log started at UTC: 2023-04-24T08:59:09+00:00
# Date,K2002 CH1,K2002 CH2,K2002 CH3,K2002 CH4,K2002 CH5,K2002 CH6,K2002 CH7,K2002 CH8,K2002 CH9,K2002 CH10,Temperature 10k Thermistor (PCB),Temperature PT100 (Room),Humidity (Ambient),Temperature humidity sensor (Ambient),Temperature in loop,TEC current,TEC voltage,Temperature setpoint
2023-04-24 08:59:27.969052,7.042547698820521,7.017780379506014,7.083611152497436,7.048118522161993,7.062855981371576,7.039260378847211,7.032700956114844,7.0575705747638064,7.021529420155507,7.020890855921803,28.046,32.102,27.47,23.39,23.252105713,0.516306400,0.937316835,23.000
2023-04-24 08:59:45.982895,7.042545357037441,7.01778023822196,7.083611491927184,7.04811678159729,7.0628551134799835,7.039260247814799,7.032702405302967,7.057570567841024,7.02152966043868,7.020893466254958,28.135,32.111,27.37,23.39,23.230895996,0.469885349,0.866862714,23.000
```

Errors are logged to the console and to `errors.log` in the working directory.

## Behaviour on errors
- **Invalid readings and timeouts** are logged and the round is skipped. The next round starts immediately.
- **Connection errors**, for example an instrument that is switched off, a USB adapter that is unplugged or a network
  outage, disconnect all instruments. The logger reconnects after `reconnect_interval` seconds and keeps trying.
- **MQTT broker outages** do not stop the logging. The data is queued and published, when the broker is back.
  Values, that can never be published (for example a device without a `base_topic`), are logged and dropped.

## Development
Install the logger with the development tools and set up the git hooks:
```bash
pip install -e ".[dev]"
pre-commit install
```

The tests do not need any instruments:
```bash
pytest
pytest --cov  # with coverage
```

Before committing, `pre-commit run --all-files` runs black, isort, pylint and mypy.

## License
This project is licensed under the GPL v3 license - see the [LICENSE](LICENSE) file for details.
