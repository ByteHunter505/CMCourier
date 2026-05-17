"""Tests para ``detect_link_speed_mbps`` (079)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from cmcourier.observability import network_info
from cmcourier.observability.network_info import detect_link_speed_mbps

pytestmark = pytest.mark.unit


def _make_stats(*ifaces: tuple[str, bool, int]) -> dict[str, Any]:
    """Construye un mock dict ``{iface: snicstats(isup, speed)}``."""
    out = {}
    for name, isup, speed in ifaces:
        st = MagicMock()
        st.isup = isup
        st.speed = speed
        out[name] = st
    return out


class TestDetectLinkSpeed:
    def test_returns_max_physical_iface_speed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_stats = _make_stats(
            ("lo", True, 0),
            ("eth0", True, 1000),
            ("docker0", True, 10000),
            ("wlan0", True, 300),
        )
        mock_psutil = MagicMock()
        mock_psutil.net_if_stats = lambda: fake_stats
        monkeypatch.setitem(__import__("sys").modules, "psutil", mock_psutil)
        assert detect_link_speed_mbps() == 1000.0

    def test_excludes_virtual_prefixes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_stats = _make_stats(
            ("lo", True, 0),
            ("docker0", True, 10000),
            ("br-abc123", True, 10000),
            ("veth0", True, 10000),
            ("vboxnet0", True, 1000),
            ("tun0", True, 100),
            ("vpn0", True, 100),
        )
        mock_psutil = MagicMock()
        mock_psutil.net_if_stats = lambda: fake_stats
        monkeypatch.setitem(__import__("sys").modules, "psutil", mock_psutil)
        assert detect_link_speed_mbps() == 0.0

    def test_excludes_iface_not_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_stats = _make_stats(
            ("eth0", False, 1000),
            ("eth1", True, 100),
        )
        mock_psutil = MagicMock()
        mock_psutil.net_if_stats = lambda: fake_stats
        monkeypatch.setitem(__import__("sys").modules, "psutil", mock_psutil)
        assert detect_link_speed_mbps() == 100.0

    def test_excludes_iface_with_zero_speed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_stats = _make_stats(
            ("eth0", True, 0),
            ("eth1", True, 100),
        )
        mock_psutil = MagicMock()
        mock_psutil.net_if_stats = lambda: fake_stats
        monkeypatch.setitem(__import__("sys").modules, "psutil", mock_psutil)
        assert detect_link_speed_mbps() == 100.0

    def test_returns_zero_when_no_interfaces(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_psutil = MagicMock()
        mock_psutil.net_if_stats = lambda: {}
        monkeypatch.setitem(__import__("sys").modules, "psutil", mock_psutil)
        assert detect_link_speed_mbps() == 0.0

    def test_handles_psutil_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def broken_stats() -> dict[str, Any]:
            raise OSError("permission denied")

        mock_psutil = MagicMock()
        mock_psutil.net_if_stats = broken_stats
        monkeypatch.setitem(__import__("sys").modules, "psutil", mock_psutil)
        assert detect_link_speed_mbps() == 0.0


class TestVirtualPrefixesIsCaseInsensitive:
    def test_uppercase_loopback_excluded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_stats = _make_stats(
            ("Loopback Pseudo-Interface 1", True, 10000),
            ("Ethernet", True, 1000),
        )
        mock_psutil = MagicMock()
        mock_psutil.net_if_stats = lambda: fake_stats
        monkeypatch.setitem(__import__("sys").modules, "psutil", mock_psutil)
        assert detect_link_speed_mbps() == 1000.0


class TestModuleExposure:
    def test_function_is_in_all(self) -> None:
        assert "detect_link_speed_mbps" in network_info.__all__
