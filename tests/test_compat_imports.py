# -*- coding: utf-8 -*-


def test_legacy_import_paths_still_work():
    from database import DatabaseManager
    from ui.main_window import MainWindow
    import ui.main_window_ui as ui_mod
    from core import utils

    assert DatabaseManager.__name__ == "DatabaseManager"
    assert MainWindow.__name__ == "MainWindow"
    assert ui_mod.MainWindowUIMixin.__name__ == "MainWindowUIMixin"
    assert callable(getattr(ui_mod.MainWindowUIMixin, "_create_ui"))
    assert callable(getattr(ui_mod.MainWindowUIMixin, "_build_preset_menu"))
    assert hasattr(ui_mod, "QFileDialog")
    assert hasattr(ui_mod, "QInputDialog")
    assert hasattr(ui_mod, "QMessageBox")
    assert callable(utils.atomic_write_text)
    assert callable(utils.reflow_subtitles)
