from __future__ import annotations

import sys

import pytest

mw_mod = pytest.importorskip("ui.main_window")
MainWindow = mw_mod.MainWindow


def test_startup_update_check_runs_only_for_frozen_enabled_build(monkeypatch) -> None:
    calls: list[bool] = []
    window = MainWindow.__new__(MainWindow)
    window.check_updates_on_startup = True
    window._check_for_updates = lambda *, interactive: calls.append(interactive)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    MainWindow._schedule_startup_update_check(window)
    assert calls == [False]

    window.check_updates_on_startup = False
    MainWindow._schedule_startup_update_check(window)
    assert calls == [False]
