from __future__ import annotations

import json
from typing import Any, TypeVar

import msgpack
from pydantic import BaseModel

from breacheye.rafa.schemas import (
    DepthOutput,
    DetectionOutput,
    FrameInput,
    HealthOutput,
    NavigationOutput,
)

T = TypeVar("T", bound=BaseModel)


def encode_msgpack(payload: BaseModel | dict[str, Any]) -> bytes:
    if isinstance(payload, BaseModel):
        data = payload.model_dump(mode="python")
    else:
        data = payload
    return msgpack.packb(data, use_bin_type=True)


def encode_json(payload: BaseModel | dict[str, Any]) -> bytes:
    if isinstance(payload, BaseModel):
        data = payload.model_dump(mode="json")
    else:
        data = payload
    return json.dumps(data, separators=(",", ":")).encode("utf-8")


def decode_json(data: bytes) -> dict[str, Any]:
    unpacked = json.loads(data.decode("utf-8"))
    if not isinstance(unpacked, dict):
        raise ValueError("JSON payload must decode to a mapping")
    return unpacked


def decode_msgpack(data: bytes) -> dict[str, Any]:
    unpacked = msgpack.unpackb(data, raw=False)
    if not isinstance(unpacked, dict):
        raise ValueError("msgpack payload must decode to a mapping")
    return unpacked


def decode_model(data: bytes, model_type: type[T]) -> T:
    return model_type.model_validate(decode_msgpack(data))


def decode_json_model(data: bytes, model_type: type[T]) -> T:
    return model_type.model_validate(decode_json(data))


def decode_frame(data: bytes) -> FrameInput:
    return decode_model(data, FrameInput)


def decode_detection(data: bytes) -> DetectionOutput:
    return decode_json_model(data, DetectionOutput)


def decode_depth(data: bytes) -> DepthOutput:
    return decode_model(data, DepthOutput)


def decode_navigation(data: bytes) -> NavigationOutput:
    return decode_json_model(data, NavigationOutput)


def decode_health(data: bytes) -> HealthOutput:
    return decode_json_model(data, HealthOutput)
