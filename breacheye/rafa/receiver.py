from __future__ import annotations

import asyncio

from breacheye.rafa.codec import decode_frame
from breacheye.rafa.schemas import FrameInput


class ZmqFrameReceiver:
    def __init__(self, endpoint: str, context=None) -> None:
        self.endpoint = endpoint
        self.context = context
        self.socket = None

    def start(self) -> None:
        import zmq
        import zmq.asyncio

        if self.context is None:
            self.context = zmq.asyncio.Context.instance()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.setsockopt(zmq.SUBSCRIBE, b"")
        self.socket.setsockopt(zmq.CONFLATE, 1)
        self.socket.connect(self.endpoint)

    async def recv(self, timeout_s: float | None = None) -> FrameInput:
        if self.socket is None:
            self.start()
        assert self.socket is not None
        if timeout_s is None:
            data = await self.socket.recv()
        else:
            data = await asyncio.wait_for(self.socket.recv(), timeout_s)
        return decode_frame(data)

    def close(self) -> None:
        if self.socket is not None:
            self.socket.close(linger=0)
            self.socket = None
