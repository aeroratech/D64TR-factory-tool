from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent, QGuiApplication, QShowEvent
from PySide6.QtWidgets import QMainWindow, QTabWidget, QWidget

from .config_tab import ConfigTab
from .info_tab import InfoTab
from .update_tab import UpdateTab


TabFactory = Callable[[], QWidget]


class MainWindow(QMainWindow):
    def __init__(
        self,
        tab_factories: tuple[TabFactory, TabFactory, TabFactory] | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("D64TR Factory Tool")
        self.resize(760, 680)
        self._shutdown_complete = False

        factories = tab_factories or (InfoTab, UpdateTab, ConfigTab)
        self._tab_widgets = tuple(factory() for factory in factories)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._tab_widgets[0], "Info")
        self.tabs.addTab(self._tab_widgets[1], "Update")
        self.tabs.addTab(self._tab_widgets[2], "Configuration")
        self.setCentralWidget(self.tabs)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._center_on_primary_screen)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._shutdown_complete:
            self._shutdown_complete = True
            for tab in self._tab_widgets:
                shutdown = getattr(tab, "shutdown", None)
                if callable(shutdown):
                    shutdown()
        super().closeEvent(event)

    def _center_on_primary_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = self.frameGeometry()
        geometry.moveCenter(screen.availableGeometry().center())
        self.move(geometry.topLeft())
