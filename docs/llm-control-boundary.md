# LLM Control Boundary

## Principle

The LLM should plan, not directly pilot raw SDK commands. It reads observations and emits structured intents. The harness owns validation, clamping, timing, and fail-safe behavior.

## Inputs To The LLM

- Latest sampled frame from `/frame/latest` or `drone.frames.llm`.
- Telemetry from `/health`, `/events`, or the future external event bus.
- Optional task context from the operator, such as "scan the room" or "look for a door."

## Outputs From The LLM

The LLM emits only `DroneCommand` JSON:

```json
{
  "type": "rc_control",
  "issued_by": "llm",
  "ttl_ms": 500,
  "payload": {
    "left_right": 0,
    "forward_back": 20,
    "up_down": 0,
    "yaw": 0,
    "duration_ms": 300
  }
}
```

## Why This Boundary Exists

The SDK supports broader movement commands and raw control strings, but an LLM can produce malformed or overconfident output. Short-lived structured actions make every model decision reversible: if the next command does not arrive, the harness hovers.

## Future Planner Work

- Add room-scan prompt/policy that alternates visual inspection, small yaw movements, hover, and forward movement only when a path is visually clear.
- Add explicit operator approval modes for first takeoff, door traversal, and low-battery continuation.
- Add perception helpers before asking the LLM to infer everything from raw frames.
