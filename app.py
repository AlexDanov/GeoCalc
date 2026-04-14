from __future__ import annotations

import ctypes
import tkinter as tk

from ui.main_window import GeoCalcApp


def enable_windows_dpi_awareness() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def main() -> None:
    enable_windows_dpi_awareness()
    root = tk.Tk()
    try:
        root.tk.call("tk", "scaling", root.winfo_fpixels("1i") / 72.0)
    except Exception:
        pass
    GeoCalcApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
