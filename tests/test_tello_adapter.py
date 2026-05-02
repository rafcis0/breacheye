import sys
import types

import pytest

from breacheye.adapters.tello import TelloAdapter


class FakeTello:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[int, ...]]] = []
        self.is_flying = False
        self.reader = object()

    def connect(self) -> None:
        self.calls.append(("connect", ()))

    def end(self) -> None:
        self.calls.append(("end", ()))

    def takeoff(self) -> None:
        self.is_flying = True
        self.calls.append(("takeoff", ()))

    def land(self) -> None:
        self.is_flying = False
        self.calls.append(("land", ()))

    def emergency(self) -> None:
        self.is_flying = False
        self.calls.append(("emergency", ()))

    def send_rc_control(self, left_right: int, forward_back: int, up_down: int, yaw: int) -> None:
        self.calls.append(("send_rc_control", (left_right, forward_back, up_down, yaw)))

    def streamon(self) -> None:
        self.calls.append(("streamon", ()))

    def streamoff(self) -> None:
        self.calls.append(("streamoff", ()))

    def get_current_state(self) -> dict[str, str]:
        return {"bat": "88", "h": "120", "time": "7", "other": "kept"}

    def get_frame_read(self):
        self.calls.append(("get_frame_read", ()))
        return self.reader


@pytest.fixture
def fake_tello(monkeypatch):
    instances: list[FakeTello] = []

    class Factory(FakeTello):
        def __init__(self) -> None:
            super().__init__()
            instances.append(self)

    module = types.SimpleNamespace(Tello=Factory)
    monkeypatch.setitem(sys.modules, "djitellopy", module)
    return instances


@pytest.mark.asyncio
async def test_connect_creates_and_connects_sdk_object(fake_tello) -> None:
    adapter = TelloAdapter()

    await adapter.connect()

    assert len(fake_tello) == 1
    assert fake_tello[0].calls == [("connect", ())]


@pytest.mark.asyncio
async def test_commands_dispatch_to_sdk(fake_tello) -> None:
    adapter = TelloAdapter()
    await adapter.connect()

    await adapter.takeoff()
    await adapter.land()
    await adapter.emergency()
    await adapter.rc_control(1, 2, 3, 4)
    await adapter.start_video()
    await adapter.stop_video()

    assert fake_tello[0].calls == [
        ("connect", ()),
        ("takeoff", ()),
        ("land", ()),
        ("emergency", ()),
        ("send_rc_control", (1, 2, 3, 4)),
        ("streamon", ()),
        ("streamoff", ()),
    ]


@pytest.mark.asyncio
async def test_get_state_maps_sdk_fields(fake_tello) -> None:
    adapter = TelloAdapter()
    await adapter.connect()
    fake_tello[0].is_flying = True

    state = await adapter.get_state()

    assert state.connected is True
    assert state.flying is True
    assert state.battery == 88
    assert state.height_cm == 120
    assert state.flight_time_s == 7
    assert state.raw["other"] == "kept"


@pytest.mark.asyncio
async def test_frame_reader_requires_connection_and_returns_sdk_reader(fake_tello) -> None:
    adapter = TelloAdapter()
    with pytest.raises(RuntimeError):
        adapter.frame_reader()

    await adapter.connect()

    assert adapter.frame_reader() is fake_tello[0].reader
