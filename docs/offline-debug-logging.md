# Offline Debug Logging

When the Mac is connected to Tello Wi-Fi, assume internet and chat access are unavailable. Every process should write JSONL logs under `logs/` so the run can be debugged after reconnecting.

## Log Files

By default, each process writes:

```text
logs/<run_id>-rafa.jsonl
logs/<run_id>-frame_publisher.jsonl
logs/<run_id>-subscriber_<channel>_<port>.jsonl
logs/<run_id>/<component>/frames/frame-00000000.jpg
logs/<run_id>/rafa/depth/frame-00000000.png
logs/<run_id>/rafa/depth_raw/frame-00000000.npy
```

Set a shared run id before a hardware test:

```bash
export BREACHEYE_RUN_ID="tello-$(date -u +%Y%m%dT%H%M%SZ)"
export BREACHEYE_LOG_DIR="logs"
```

Write a preflight snapshot before leaving normal Wi-Fi:

```bash
breacheye offline preflight --run-id "$BREACHEYE_RUN_ID" --log-dir "$BREACHEYE_LOG_DIR"
```

This writes `logs/<run_id>/run-metadata.json` and `logs/<run_id>-offline.jsonl`. The metadata captures git commit/status, selected environment variables, model file existence/sizes, expected port state, relevant processes, disk space, and current artifact counts.

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
- frame ids, JPEG byte sizes, and saved received-frame image paths
- depth visualization PNG paths for each depth output
- raw `float32` depth `.npy` paths for post-run mapping
- decode failures
- detection/depth/navigation fallbacks
- every publish event with frame id, action, counts, and health summary

Frame publisher:

- startup endpoint and cadence
- every published frame id, dimensions, payload size, and saved sent-frame image path
- shutdown

Subscriber probe:

- subscription target
- each received payload size and decoded content

Offline preflight:

- git commit, branch, and dirty status
- environment variables for local models and log paths
- file existence and byte sizes for model paths
- expected port state for ZMQ, harness API, and Qwen server
- relevant local processes
- disk free space
- current artifact counts

Post-run map artifact:

```bash
python ai/depth_log_map.py --run-id "$BREACHEYE_RUN_ID" --log-dir logs
```

This writes `logs/<run_id>/map/relative-depth-point-cloud.ply` and `logs/<run_id>/map/relative-depth-summary.json` from saved `depth_raw` arrays.

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
export BREACHEYE_DEPTH_ANYTHING_PATH=models/depth-anything-v2-small-hf
export BREACHEYE_DEPTH_ANYTHING_DEVICE=mps
export BREACHEYE_RUN_ID="model-$(date -u +%Y%m%dT%H%M%SZ)"
breacheye offline preflight --run-id "$BREACHEYE_RUN_ID"
breacheye rafa --mode models --run-id "$BREACHEYE_RUN_ID"
python integration/frame_publisher.py --frames 5 --fps 1 --run-id "$BREACHEYE_RUN_ID"
```

After reconnecting, inspect:

```bash
tail -n 100 logs/${BREACHEYE_RUN_ID}-rafa.jsonl
find logs/${BREACHEYE_RUN_ID} -type f | sort | head
```

Then create a single bundle to share/debug:

```bash
breacheye offline bundle --run-id "$BREACHEYE_RUN_ID" --log-dir logs
ls -lh logs/${BREACHEYE_RUN_ID}-offline-bundle.tar.gz
```

## Model-Mode Start Order

For the current Qwen + Depth Anything path:

```bash
export BREACHEYE_RUN_ID="tello-$(date -u +%Y%m%dT%H%M%SZ)"
export BREACHEYE_LOG_DIR=logs
export BREACHEYE_QWEN_MODEL=models/qwen3-vl-2b/Qwen3-VL-2B-Instruct-Q4_K_M.gguf
export BREACHEYE_QWEN_MMPROJ=models/qwen3-vl-2b/mmproj-F16.gguf
export BREACHEYE_QWEN_SERVER_URL=http://127.0.0.1:56262
export BREACHEYE_QWEN_MAX_TOKENS=32
export BREACHEYE_DEPTH_ANYTHING_PATH=models/depth-anything-v2-small-hf
export BREACHEYE_DEPTH_ANYTHING_DEVICE=mps
```

Terminal 1:

```bash
llama-server \
  -m "$BREACHEYE_QWEN_MODEL" \
  --mmproj "$BREACHEYE_QWEN_MMPROJ" \
  --host 127.0.0.1 --port 56262 \
  --ctx-size 4096 -ngl 99
```

Terminal 2:

```bash
breacheye offline preflight --run-id "$BREACHEYE_RUN_ID"
breacheye rafa --mode models --run-id "$BREACHEYE_RUN_ID"
```

Terminal 3, synthetic dry run:

```bash
python integration/frame_publisher.py --frames 10 --fps 1 --run-id "$BREACHEYE_RUN_ID"
```

Terminal 3, Tello run:

```bash
python integration/frame_publisher.py --tello --fps 5 --run-id "$BREACHEYE_RUN_ID"
```

Terminal 4, optional probes:

```bash
python shared/zmq_test_sub.py --port 5558 --channel navigation --count 20 --run-id "$BREACHEYE_RUN_ID"
python shared/zmq_test_sub.py --port 5559 --channel health --count 20 --run-id "$BREACHEYE_RUN_ID"
```
