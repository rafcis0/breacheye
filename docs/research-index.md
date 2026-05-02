# Research Index

This file records the outside references used to shape the harness. It is not a complete Tello bibliography; it is the source trail for the implementation decisions in this repo.

## Primary SDK Documentation

Ryze Tello SDK 2.0 User Guide:

https://dl-cdn.ryzerobotics.com/downloads/Tello/Tello%20SDK%202.0%20User%20Guide.pdf

Implementation takeaways:

- Enter SDK mode before control by sending the command-mode instruction over UDP.
- SDK control traffic uses the drone at `192.168.10.1` and UDP port `8889`.
- State packets are received on UDP `8890`.
- Video is received on UDP `11111` after enabling streaming.
- `streamon`, `streamoff`, `takeoff`, `land`, and `emergency` are control commands.
- The SDK supports more movement commands than this harness exposes; v1 intentionally keeps a smaller action set.

## Python Wrapper

DJITelloPy API reference:

https://djitellopy.readthedocs.io/en/latest/tello/

DJITelloPy repository:

https://github.com/damiafuentes/DJITelloPy

Implementation takeaways:

- DJITelloPy wraps the official SDK and already handles command responses, parsed state packets, and background frame reads.
- `send_rc_control(left_right, forward_back, up_down, yaw)` maps directly to four remote-control velocity channels.
- DJITelloPy documents channel limits as `-100..100`; BreachEye clamps to a lower default for early autonomous tests.
- `send_keepalive()` exists to avoid the Tello's command-timeout landing behavior.
- `streamon()` plus `get_frame_read()` provides the frame source used by `TelloVideoPump`.

## Video Stream Notes

Tello-Python repository:

https://github.com/xg590/Tello-Python

MATLAB Ryze Tello video troubleshooting:

https://kr.mathworks.com/help/matlab/supportpkg/troubleshoot-video-stream-access-ryzeio.html

Implementation takeaways:

- Community examples and vendor support docs agree that the FPV stream arrives over UDP `11111`.
- Firewall rules commonly affect telemetry/video even when commands still work.
- The harness keeps one decoded video source and fans out full-rate and sampled paths, because the frontend needs continuous video while the LLM only needs occasional frames.

## Video/Community Material

Some community posts and tutorial videos focus on basic Tello connection, takeoff/land, camera setup, and voice/model control experiments. They are useful for operator workflow expectations, but the repo treats the official SDK guide and DJITelloPy documentation as authoritative for ports, commands, and API behavior.

Implementation takeaways:

- Keep setup scripts conservative and obvious: connect, take off, hover/scan briefly, land.
- Make video troubleshooting visible in the docs because beginners often get command control working before UDP video works.
- Keep the future model boundary explicit so demos do not drift into sending free-form generated text to the drone.
