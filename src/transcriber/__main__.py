"""Desktop application and packaged MCP server entry point."""

from __future__ import annotations

import sys


def main() -> int:
    # The stdio MCP process must not initialise Qt or construct the GUI.
    if "--mcp-server" in sys.argv[1:]:
        sys.argv.remove("--mcp-server")
        from transcriber.mcp_server import main as mcp_main
        return mcp_main()

    from PySide6.QtWidgets import QApplication, QMessageBox

    from transcriber.bootstrap import build_services
    from transcriber.ui.main_window import MainWindow
    from transcriber.ui.theme import stylesheet

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
    raise SystemExit(main())
