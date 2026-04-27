from __future__ import annotations


def main() -> None:
    """
    PyInstaller entrypoint for the Qt GUI.

    Important: this file must NOT rely on package-relative imports.
    """
    from yxl_lace.ui_qt.app import main as ui_main

    ui_main()


if __name__ == "__main__":
    main()

