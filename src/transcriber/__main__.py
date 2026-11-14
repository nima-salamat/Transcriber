"""Desktop application entry point."""

from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from transcriber.bootstrap import build_services
from transcriber.ui.main_window import MainWindow
from transcriber.ui.theme import stylesheet


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Transcriber")
    app.setOrganizationName("Transcriber")
    app.setStyle("Fusion")
    services = build_services()
    theme = services["settings"].settings.theme
    app.setStyleSheet(stylesheet("light" if theme == "light" else "dark"))
    try:
        window = MainWindow(
            services["paths"], services["settings"], services["history"],
            services["database"], services["model_manager"],
        )
    except Exception as exc:
        services["logger"].exception("Application startup failed")
        QMessageBox.critical(None, "Transcriber could not start", str(exc))
        return 1
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
