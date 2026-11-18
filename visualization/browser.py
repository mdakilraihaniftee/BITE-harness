"""Optional browser launch that cannot take over the inference terminal."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading


def open_dashboard_browser(url: str) -> bool:
    """Request a detached graphical opener, never a terminal-browser fallback.

    On a remote/headless Linux host the URL is opened manually on the user's
    workstation after port forwarding. Browser failures are advisory and must
    not gate model execution or consume its stdin.
    """
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        print("Automatic browser opening skipped: this host has no graphical display. "
              "Forward the dashboard port in VS Code's Ports tab and open the URL in your desktop browser.", flush=True)
        return False
    if sys.platform == "darwin":
        opener = shutil.which("open")
        command = [opener, url] if opener else None
    elif os.name == "nt":
        command = None
    else:
        opener = shutil.which("xdg-open")
        command = [opener, url] if opener else None
    if command is None and os.name != "nt":
        print("No graphical browser opener found. Open the printed dashboard URL manually.", flush=True)
        return False

    def launch() -> None:
        try:
            if os.name == "nt":
                os.startfile(url)  # type: ignore[attr-defined]
                return
            env = dict(os.environ)
            # BROWSER commonly points at a stale VS Code IPC helper or lynx.
            # The desktop opener chooses the registered graphical browser.
            env.pop("BROWSER", None)
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       start_new_session=True, env=env)
            try:
                code = process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                return  # A running GUI must not be killed or block inference.
            if code:
                print("The browser opener failed. Inference continues; open the printed URL manually.", flush=True)
        except Exception:
            print("The browser could not be opened. Inference continues; open the printed URL manually.", flush=True)

    threading.Thread(target=launch, name="argus-browser-opener", daemon=True).start()
    return True
