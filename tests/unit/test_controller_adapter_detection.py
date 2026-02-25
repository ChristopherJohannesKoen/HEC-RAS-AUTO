from __future__ import annotations

import pytest

from src.ras.controller_adapter import HECControllerError, HECRASControllerAdapter


def test_detect_progid_prefers_ras67(monkeypatch) -> None:
    adapter = HECRASControllerAdapter()

    def fake_available(pid: str) -> bool:
        return pid == "RAS67.HECRASController"

    monkeypatch.setattr(adapter, "_com_available", fake_available)
    assert adapter.detect_progid() == "RAS67.HECRASController"


def test_detect_progid_raises_when_missing(monkeypatch) -> None:
    adapter = HECRASControllerAdapter()
    monkeypatch.setattr(adapter, "_com_available", lambda pid: False)
    with pytest.raises(HECControllerError):
        adapter.detect_progid()
