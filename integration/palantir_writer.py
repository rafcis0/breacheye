from __future__ import annotations

import argparse
import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Optional

import dotenv
import requests
import zmq

from breacheye.rafa.schemas import Detection, DetectionOutput


logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("palantir_writer")


class PalantirWriter:
    """Batch-push TacticalPoi objects to Palantir Foundry from ZMQ DetectionOutput stream."""

    def __init__(
        self,
        host: str,
        token: str,
        ontology: str = "default",
        action: str = "create-tactical-poi",
        scan_id: Optional[str] = None,
        flush_interval: float = 5.0,
        max_queue: int = 500,
        zmq_port: int = 5556,
    ) -> None:
        self._host = host.rstrip("/")
        if not self._host.startswith("https://"):
            raise ValueError("FOUNDRY_HOST must use HTTPS")
        self._token = token
        self._ontology = ontology
        self._action = action
        self._scan_id = scan_id or str(uuid.uuid4())
        self._flush_interval = flush_interval
        self._zmq_port = zmq_port

        self._queue: deque[dict] = deque(maxlen=max_queue)
        self._queue_lock = threading.Lock()
        self._stop_event = threading.Event()

        self._seen: dict[tuple, tuple[float, float]] = {}
        self._dedup_count = 0
        self._pushed_count = 0
        self._failed_count = 0
        self._retry_count = 0

        self._poi_counters: dict[str, int] = defaultdict(int)

        self._auth_failed = False
        self._last_auth_warn_ts: float = 0.0
        self._action_missing = False
        self._last_action_warn_ts: float = 0.0

    def start(self) -> None:
        self._stop_event.clear()
        threading.Thread(target=self._zmq_loop, daemon=True, name="palantir-zmq").start()
        threading.Thread(target=self._flush_loop, daemon=True, name="palantir-flush").start()
        logger.info("PalantirWriter started scan_id=%s", self._scan_id)

    def stop(self) -> None:
        self._stop_event.set()
        # Give threads a moment to exit, then do a final flush
        time.sleep(0.5)
        self._drain_and_push()
        logger.info("PalantirWriter stopped. Final stats: %s", self.stats())

    def stats(self) -> dict:
        with self._queue_lock:
            queued = len(self._queue)
        return {
            "pushed": self._pushed_count,
            "queued": queued,
            "failed": self._failed_count,
            "retries": self._retry_count,
            "deduplicated": self._dedup_count,
        }

    def _zmq_loop(self) -> None:
        context = zmq.Context.instance()
        socket = context.socket(zmq.SUB)
        socket.setsockopt(zmq.SUBSCRIBE, b"")
        socket.setsockopt(zmq.RCVTIMEO, 500)
        endpoint = f"tcp://localhost:{self._zmq_port}"
        socket.connect(endpoint)
        logger.info("ZMQ subscriber connected to %s", endpoint)
        try:
            while not self._stop_event.is_set():
                try:
                    raw = socket.recv()
                except zmq.Again:
                    continue
                try:
                    data = json.loads(raw)
                    output = DetectionOutput.model_validate(data)
                except (json.JSONDecodeError, ValueError) as exc:
                    logger.warning("ZMQ frame skipped: %s", exc)
                    continue
                for detection in output.detections:
                    poi = self._dedup(detection, output.timestamp)
                    if poi is not None:
                        with self._queue_lock:
                            self._queue.append(poi)
        finally:
            socket.close(linger=0)
            logger.debug("ZMQ loop exited")

    def _flush_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._flush_interval)
            self._drain_and_push()

    def _drain_and_push(self) -> None:
        if self._auth_failed:
            now = time.time()
            if now - self._last_auth_warn_ts >= 30.0:
                logger.warning(
                    "Auth failed — skipping Foundry push. Reset _auth_failed to resume."
                )
                self._last_auth_warn_ts = now
            return

        if self._action_missing:
            now = time.time()
            if now - self._last_action_warn_ts >= 30.0:
                logger.warning(
                    "Foundry action '%s' not found — waiting for Palantir staff to create it.",
                    self._action,
                )
                self._last_action_warn_ts = now
            return

        with self._queue_lock:
            batch = list(self._queue)
            self._queue.clear()

        if not batch:
            return

        success = self._push_batch(batch)
        if not success:
            # Put items back at the front, up to maxlen
            with self._queue_lock:
                for poi in reversed(batch):
                    self._queue.appendleft(poi)

        now = time.time()
        self._seen = {k: v for k, v in self._seen.items() if now - v[0] < 2.0}

    def _push_batch(self, pois: list[dict]) -> bool:
        url = (
            f"{self._host}/api/v2/ontologies/{self._ontology}"
            f"/actions/{self._action}/applyBatch"
        )
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        body = {"requests": [{"parameters": poi} for poi in pois]}
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=10)
        except requests.ConnectionError:
            logger.warning("Foundry connection refused — will retry next cycle")
            self._retry_count += 1
            return False
        except requests.Timeout:
            logger.warning("Foundry request timed out — will retry next cycle")
            self._retry_count += 1
            return False

        if resp.status_code in (200, 204):
            self._pushed_count += len(pois)
            logger.info("Pushed %d POIs to Foundry", len(pois))
            return True
        elif resp.status_code == 404:
            logger.error(
                "Foundry action '%s' not found — ask Palantir staff to create it.",
                self._action,
            )
            self._action_missing = True
            self._failed_count += len(pois)
            return False
        elif resp.status_code in (401, 403):
            logger.error(
                "Foundry auth failed (%d) — disabling pushes. Fix token and reset _auth_failed.",
                resp.status_code,
            )
            self._auth_failed = True
            self._failed_count += len(pois)
            return False
        elif resp.status_code == 429:
            logger.warning("Rate limited by Foundry — will retry next cycle")
            self._retry_count += 1
            return False
        elif 500 <= resp.status_code < 600:
            logger.warning("Foundry error %d — will retry next cycle", resp.status_code)
            self._retry_count += 1
            return False
        else:
            logger.warning("Foundry unexpected status %d", resp.status_code)
            self._retry_count += 1
            return False

    def _dedup(self, detection: Detection, timestamp: float) -> Optional[dict]:
        cx = (detection.bbox_2d.x1 + detection.bbox_2d.x2) // 2
        cy = (detection.bbox_2d.y1 + detection.bbox_2d.y2) // 2
        key = (detection.category, cx // 80, cy // 80)

        if key in self._seen:
            prev_ts, _ = self._seen[key]
            if timestamp - prev_ts < 2.0:
                self._dedup_count += 1
                return None
        self._seen[key] = (timestamp, detection.confidence)
        return self._to_poi(detection, cx, cy)

    def _to_poi(self, detection: Detection, cx: int, cy: int) -> dict:
        # Fake 2D-to-3D: normalize pixel coords to a 10x10m room footprint; no depth available yet
        pos_x = (cx / 960) * 10.0
        pos_y = (cy / 720) * 10.0
        return {
            "poiId": self._next_poi_id(detection.category),
            "scanId": self._scan_id,
            "category": detection.category,
            "label": detection.label,
            "confidence": detection.confidence,
            "posX": round(pos_x, 4),
            "posY": round(pos_y, 4),
            "posZ": 0.0,
            "floor": 0,
            "threatLevel": detection.threat_level,
            "createdAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def _next_poi_id(self, category: str) -> str:
        self._poi_counters[category] += 1
        return f"{category}-{self._poi_counters[category]:03d}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Palantir Foundry POI batch writer")
    parser.add_argument("--zmq-port", type=int, default=5556)
    parser.add_argument("--flush-interval", type=float, default=5.0)
    parser.add_argument("--max-queue", type=int, default=500)
    parser.add_argument("--scan-id", default=None)
    args = parser.parse_args()

    dotenv.load_dotenv()

    host = os.environ.get("FOUNDRY_HOST")
    token = os.environ.get("FOUNDRY_TOKEN")
    if not host:
        parser.error("FOUNDRY_HOST is not set")
    if not token:
        parser.error("FOUNDRY_TOKEN is not set")

    ontology = os.environ.get("FOUNDRY_ONTOLOGY", "default")
    action = os.environ.get("FOUNDRY_ACTION_CREATE_POI", "create-tactical-poi")

    writer = PalantirWriter(
        host=host,
        token=token,
        ontology=ontology,
        action=action,
        scan_id=args.scan_id,
        flush_interval=args.flush_interval,
        max_queue=args.max_queue,
        zmq_port=args.zmq_port,
    )
    writer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        writer.stop()


if __name__ == "__main__":
    main()
