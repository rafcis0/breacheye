# Offline Debug Logging

When the Mac is connected to Tello Wi-Fi, assume internet and chat access are unavailable. Every process should write JSONL logs under `logs/` so the run can be debugged after reconnecting.

## Log Files

By default, each process writes:

```text
logs/<run_id>-rafa.jsonl
logs/<run_id>-frame_publisher.jsonl
logs/<run_id>-subscriber_<channel>_<port>.jsonl
```

Set a shared run id before a hardware test:

```bash
export BREACHEYE_RUN_ID="tello-$(date -u +%Y%m%dT%H%M%SZ)"
export BREACHEYE_LOG_DIR="logs"
```

Then pass the same run id explicitly when useful:

```bash
breacheye rafa --mode stub --run-id "$BREACHEYE_RUN_ID" --log-dir logs
python integration/frame_publisher.py --tello --run-id "$BREACHEYE_RUN_ID" --log-dir logs
python shared/zmq_test_sub.py --port 5558 --channel navigation --count 20 --run-id "$BREACHEYE_RUN_ID"
```

## What Gets Logged

Rafa pipeline:

- startup mode and ports
- adapter/model fallback decisions
- frame receive timeouts
- frame ids and JPEG byte sizes
- decode failures
- detection/depth/navigation fallbacks
- every publish event with frame id, action, counts, and health summary

Frame publisher:

- startup endpoint and cadence
- every published frame id, dimensions, and payload size
- shutdown

Subscriber probe:

- subscription target
- each received payload size and decoded content

## Hardware Run Checklist

Before disconnecting from internet:

```bash
pytest -q
breacheye rafa doctor
```

For stub contract verification:

```bash
export BREACHEYE_RUN_ID="stub-$(date -u +%Y%m%dT%H%M%SZ)"
breacheye rafa --mode stub --run-id "$BREACHEYE_RUN_ID"
python integration/frame_publisher.py --frames 30 --fps 5 --run-id "$BREACHEYE_RUN_ID"
```

For model fallback verification:

```bash
export BREACHEYE_QWEN_MODEL=models/qwen3-vl-2b/Qwen3-VL-2B-Instruct-Q4_K_M.gguf
export BREACHEYE_QWEN_MMPROJ=models/qwen3-vl-2b/mmproj-F16.gguf
export BREACHEYE_RUN_ID="model-$(date -u +%Y%m%dT%H%M%SZ)"
breacheye rafa --mode models --run-id "$BREACHEYE_RUN_ID"
python integration/frame_publisher.py --frames 5 --fps 1 --run-id "$BREACHEYE_RUN_ID"
```

After reconnecting, inspect:

```bash
tail -n 100 logs/${BREACHEYE_RUN_ID}-rafa.jsonl
```
