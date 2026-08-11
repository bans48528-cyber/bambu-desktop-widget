# Bambu Desktop Widget

Windows desktop widget for showing Bambu Lab printer status through local MQTT.

## Features

- Runs as part of the Windows desktop layer
- Shows printer state, job name, progress, remaining time, ETA, and layer count
- Supports dragging and resizing the widget
- Supports configurable opacity and base font size
- Uses local MQTT connection on port `8883`
- Can try cached IP first, then discover the printer again when the IP changes
- Shows a lightweight in-widget completion notice when a print finishes

## Start

Double-click:

```text
start-native.vbs
```

For debugging with console output, run:

```text
start-native.bat
```

## Configuration

Right-click the widget and choose the settings menu.

Local settings are saved in `config.json`. This file is ignored by Git because it may contain private printer information and the access code.

Use `config.example.json` as a template when setting up a fresh copy.

Configurable fields include:

- Printer IP
- Printer serial number
- Access code
- Display name
- Remaining time unit
- Opacity
- Base font size
- Window position and size

## Privacy

Do not publish `config.json`, `config.lock`, or `startup.log`.

The real printer access code should stay only on your local machine.
