# Tello Hardware Runbook

## Before Flight

- Use a clear indoor area with prop guards installed.
- Connect the laptop to the `Tello-XXXXXX` Wi-Fi network.
- Confirm the battery is high enough for a short test flight.
- Make sure local firewall rules allow inbound UDP state/video traffic, especially ports `8890` and `11111`.
- Keep a human ready to stop the harness or trigger `emergency`.

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[hardware,test]"
```

## Simulator Smoke Test

```bash
breacheye smoke --mode sim
pytest
```

## Hardware Smoke Test

Run this only after the simulator path passes:

```bash
breacheye smoke --mode tello
```

The smoke sequence connects, starts the runtime, takes off, performs a small yaw scan through the same safe command schema used by the API, and lands.

## API Flight

Start the harness:

```bash
breacheye serve --mode tello --host 127.0.0.1 --port 8000
```

Take off:

```bash
curl -X POST http://127.0.0.1:8000/commands \
  -H 'content-type: application/json' \
  -d '{"type":"takeoff","issued_by":"operator"}'
```

Hover:

```bash
curl -X POST http://127.0.0.1:8000/commands \
  -H 'content-type: application/json' \
  -d '{"type":"hover","issued_by":"operator"}'
```

Land:

```bash
curl -X POST http://127.0.0.1:8000/commands \
  -H 'content-type: application/json' \
  -d '{"type":"land","issued_by":"operator"}'
```

Emergency motor stop:

```bash
curl -X POST http://127.0.0.1:8000/commands \
  -H 'content-type: application/json' \
  -d '{"type":"emergency","issued_by":"operator"}'
```

## Full Loop Flight

Use this after `breacheye smoke --mode tello` passes. The launcher keeps one Tello owner: the harness connects to the drone, and the frame publisher reads sampled JPEGs from the harness API.

```bash
export BREACHEYE_RUN_ID="tello-$(date -u +%Y%m%dT%H%M%SZ)"
breacheye fly --mode tello --rafa-mode models --fps 5 --run-id "$BREACHEYE_RUN_ID"
```

Only add automatic takeoff for a clear test area with a human ready to intervene:

```bash
breacheye fly --mode tello --rafa-mode models --fps 2 --run-id "$BREACHEYE_RUN_ID" --auto-takeoff
```

Auto-takeoff climbs an extra 100 cm by default to reduce ground-effect drift. Use `--takeoff-climb-cm 0` to disable or `--takeoff-climb-cm 120` to tune it for the room.

Simulator rehearsal:

```bash
breacheye fly --mode sim --rafa-mode stub --duration-s 20
```

For non-flight demos, use the fallback launcher instead:

```bash
breacheye demo --mode live --fps 5
breacheye demo --mode recorded --video demo/sample.mp4 --duration-s 20
breacheye demo --mode mock --duration-s 20
```

`demo --mode live` starts the live stack but does not issue takeoff; use `fly --auto-takeoff` for physical flight.

## Troubleshooting

- If commands work but telemetry/video do not, verify firewall access to UDP `8890` and `11111`.
- If `streamon` fails with an unknown command, update the Tello firmware through the official app.
- If video is delayed, prefer the sampled-frame endpoint for control and reserve MJPEG for humans.
- If the drone does not respond, reconnect to Tello Wi-Fi and restart the harness so SDK mode is re-entered cleanly.
