from PySide6.QtWidgets import QWidget

from d64tr_factory_tool.main_window import MainWindow


class FakeTab(QWidget):
    def __init__(self):
        super().__init__()
        self.shutdown_called = 0
        self.started_after_shutdown = 0

    def shutdown(self):
        self.shutdown_called += 1


def make_factories(created_tabs):
    def factory():
        tab = FakeTab()
        created_tabs.append(tab)
        return tab

    return (factory, factory, factory)


def test_main_window_has_exactly_three_tabs_in_required_order(qtbot):
    created_tabs = []
    window = MainWindow(tab_factories=make_factories(created_tabs))
    qtbot.addWidget(window)

    assert window.windowTitle() == "D64TR Factory Tool"
    assert window.tabs.count() == 3
    assert [window.tabs.tabText(i) for i in range(3)] == [
        "Info",
        "Update",
        "Configuration",
    ]


def test_main_window_uses_application_icon(qtbot):
    created_tabs = []
    window = MainWindow(tab_factories=make_factories(created_tabs))
    qtbot.addWidget(window)

    assert not window.windowIcon().isNull()


def test_close_shuts_down_every_tab_once(qtbot):
    created_tabs = []
    window = MainWindow(tab_factories=make_factories(created_tabs))
    qtbot.addWidget(window)
    window.show()

    window.close()

    assert all(tab.shutdown_called == 1 for tab in created_tabs)
    assert all(tab.started_after_shutdown == 0 for tab in created_tabs)


def test_default_window_builds_real_tabs_without_hidden_test_tab(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)

    assert window.tabs.count() == 3
    assert all(window.tabs.isTabVisible(index) for index in range(3))
