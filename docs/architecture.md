# BreachEye Harness Architecture

## Goal

BreachEye is a narrow safety harness between an operator or LLM controller and a Ryze/DJI Tello. The drone should never receive arbitrary model output. Controllers submit structured actions, the harness validates them, then a drone adapter turns them into SDK calls.

## Research Notes

- The Tello SDK guide describes a UDP control protocol. SDK mode starts by sending `command` to UDP port `8889`; state packets arrive on `8890`; video is sent to `11111` after `streamon`.
- The guide divides commands into control, set, and read commands. This harness only exposes the subset needed for safe first-flight experiments.
- DJITelloPy wraps the official SDK, parses state packets, provides background frame reads, and exposes `send_rc_control` for four-channel velocity control.
- DJITelloPy documents RC channel limits as `-100..100`; the harness deliberately clamps lower by default.
- The Tello lands automatically after a command timeout. The harness uses keepalive/watchdog behavior so a quiet controller does not accidentally become the flight policy.

Sources:

- Ryze Tello SDK 2.0 User Guide: https://dl-cdn.ryzerobotics.com/downloads/Tello/Tello%20SDK%202.0%20User%20Guide.pdf
- DJITelloPy API reference: https://djitellopy.readthedocs.io/en/latest/tello/
- DJITelloPy repository: https://github.com/damiafuentes/DJITelloPy

## Process Boundaries

- `DroneAdapter`: hardware boundary. `TelloAdapter` talks to DJITelloPy; `SimAdapter` records commands and simulates enough state for tests.
- `SafetyController`: validation and execution boundary. It clamps velocity, enforces TTL/duration, inserts hover after RC movement, publishes results, and runs the watchdog.
- `AsyncEventBus`: in-process message bus. It gives us topic boundaries now and a clear migration path to Redis, NATS, or another external bus later.
- `FrameStore`: video fanout. It keeps the latest full JPEG for frontend display and the latest sampled JPEG for model input.
- `FastAPI service`: local integration surface for teammate tools, frontend work, and future planner processes.

## Command Policy

Raw SDK strings are intentionally not part of the public API. The public command schema is:

- `takeoff`
- `land`
- `emergency`
- `hover`
- `rc_control`

`rc_control` uses left/right, forward/back, up/down, and yaw velocity channels plus a short duration. The controller sends hover immediately after each movement duration expires.

## Video Policy

The drone produces one video stream. The harness decodes it once, then fans it out:

- Full/latest frames for human frontend display through `/video.mjpeg`.
- Sampled frames for LLM or vision control through `/frame/latest` and `drone.frames.llm`.

This keeps the LLM path low bandwidth while preserving full video for a UI.
