# Development Context

## Environment Setup

```bash
# Python deps
pip install djitellopy pyzmq msgpack opencv-python-headless numpy

# Rafa's deps (his track, but useful to know)
pip install moondream torch torchvision

# Palantir (if integrating)
pip install foundry-platform-python
```

## Running the System

### Tello Connection

```bash
# 1. Power on Tello
# 2. Connect Mac WiFi to TELLO-XXXXXX network
# 3. Test connection:
python -c "from djitellopy import Tello; t = Tello(); t.connect(); print(f'Battery: {t.get_battery()}%')"
```

Tello creates its own WiFi. For internet (Palantir API), use USB WiFi adapter or phone hotspot on second interface.

### Frame Publisher (Cooper's C1)

```bash
# Live from Tello
python integration/frame_publisher.py

# Mock from video file (no drone needed)
python integration/frame_publisher.py --mock demo/sample_flight.mp4

# Mock from static images
python integration/frame_publisher.py --mock-images demo/frames/
```

### Subscriber Test

```bash
# Verify frames are flowing
python shared/zmq_test_sub.py --port 5555 --channel frames

# Verify detections
python shared/zmq_test_sub.py --port 5556 --channel detections
```

### Mock Data Generation

```bash
# Generate mock detection JSON (no AI needed)
python demo/mock_detections.py --frames 100 --pois 15

# Generate mock navigation decisions
python demo/mock_navigation.py --pattern room_sweep
```

## ZMQ Quick Test

```python
# Publisher (Rafa side test)
import zmq, json
ctx = zmq.Context()
pub = ctx.socket(zmq.PUB)
pub.bind("tcp://*:5556")
pub.send_json({"frame_id": 1, "detections": [], "processing_ms": 0})

# Subscriber (Cooper side test)
sub = ctx.socket(zmq.SUB)
sub.connect("tcp://localhost:5556")
sub.setsockopt_string(zmq.SUBSCRIBE, "")
msg = sub.recv_json()
```

## Testing Protocol

- **Cooper tests without Rafa:** Mock detection/nav JSON on ZMQ ports. State machine, UI, Palantir all testable with fake data.
- **Rafa tests without Cooper:** Feed sample images from demo/frames/. All models run standalone.
- **Integration test:** Both running, real ZMQ. Verify frame -> detection -> nav -> command flow.

## Ports

| Port | Channel | Owner |
|------|---------|-------|
| 5555 | frames | Cooper publishes |
| 5556 | detections | Rafa publishes |
| 5557 | depth | Rafa publishes |
| 5558 | navigation | Rafa publishes |
| 5559 | health | Rafa publishes |

## Tello SDK Quick Reference

```python
from djitellopy import Tello

t = Tello()
t.connect()
t.streamon()

# Telemetry
t.get_battery()      # int, percent
t.get_height()       # int, cm
t.get_flight_time()  # int, seconds
t.get_temperature()  # int, celsius

# Movement (all in cm or degrees)
t.takeoff()
t.move_forward(50)   # 50cm
t.rotate_clockwise(90)
t.land()
t.emergency()        # KILL MOTORS (drone falls)

# Video
frame = t.get_frame_read().frame  # numpy BGR array
```
