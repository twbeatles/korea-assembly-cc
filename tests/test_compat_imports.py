# -*- coding: utf-8 -*-


def test_legacy_import_paths_still_work():
    from database import DatabaseManager
    from ui.main_window import MainWindow
    from core import utils

    assert DatabaseManager.__name__ == "DatabaseManager"
    assert MainWindow.__name__ == "MainWindow"
    assert callable(utils.atomic_write_text)
    assert callable(utils.reflow_subtitles)
