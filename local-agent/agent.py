"""
J.A.R.V.I.S. desktop agent — runs on YOUR LAPTOP.

This is the "hands" node. It dials OUT to your Jarvis server, long-polls for
commands you've already approved on your phone, runs them locally, and posts
the result back. It never opens a port — nothing new is attackable.

Run on the laptop (Python 3.10+, `pip install requests`):

    set JARVIS_URL=http://localhost:8000          (or your Tailscale https URL)
    set JARVIS_API_KEY=your-api-key-from-.env
    python agent.py

Then from your phone: "Jarvis, open Spotify on my computer" -> approve on
phone -> this agent opens it.

Safety: this agent only performs a fixed allowlist of safe local actions
(open app/website, system report, search, lock screen). It does NOT run
arbitrary shell commands. Extend the ACTIONS dict consciously.
"""
import os
import platform
import subprocess
import time
import urllib.parse
import webbrowser

import requests

URL = os.environ.get("JARVIS_URL", "http://localhost:8000").rstrip("/")
KEY = os.environ.get("JARVIS_API_KEY", "")
HEADERS = {"X-API-Key": KEY, "Content-Type": "application/json"}

APP_ALIASES = {
    "Windows": {"spotify":"spotify","chrome":"chrome","edge":"msedge","notepad":"notepad",
                "calculator":"calc","vscode":"code","code":"code","explorer":"explorer",
                "terminal":"wt","cmd":"cmd","word":"winword","excel":"excel"},
    "Darwin": {"spotify":"Spotify","chrome":"Google Chrome","safari":"Safari",
               "vscode":"Visual Studio Code","code":"Visual Studio Code","finder":"Finder",
               "notes":"Notes","terminal":"Terminal","calculator":"Calculator"},
    "Linux": {"spotify":"spotify","chrome":"google-chrome","firefox":"firefox",
              "vscode":"code","code":"code","terminal":"x-terminal-emulator","files":"nautilus"},
}


def open_application(params):
    app = str(params.get("name", "")).lower().strip()
    if not app:
        return "No app name given."
    system = platform.system()
    target = APP_ALIASES.get(system, {}).get(app, app)
    try:
        if system == "Windows":
            subprocess.Popen(f'start "" "{target}"', shell=True)
        elif system == "Darwin":
            subprocess.Popen(["open", "-a", target])
        else:
            subprocess.Popen([target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Opened {app} on the laptop."
    except Exception as e:
        return f"Couldn't open {app}: {e}"


def open_website(params):
    url = str(params.get("url", "")).strip()
    if not url:
        return "No URL given."
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    webbrowser.open(url)
    return f"Opened {url} on the laptop."


def search_web(params):
    q = str(params.get("query", "")).strip()
    if not q:
        return "No query given."
    webbrowser.open("https://www.google.com/search?q=" + urllib.parse.quote(q))
    return f"Searched the web for: {q}"


def system_report(_params):
    try:
        import psutil
    except ImportError:
        return "Install psutil on the laptop for system reports (pip install psutil)."
    cpu = psutil.cpu_percent(interval=0.4)
    mem = psutil.virtual_memory()
    parts = [f"CPU {cpu:.0f}%", f"memory {mem.percent:.0f}%"]
    batt = psutil.sensors_battery()
    if batt:
        parts.append(f"battery {batt.percent:.0f}% {'charging' if batt.power_plugged else 'on battery'}")
    return "Laptop status: " + ", ".join(parts) + "."


def lock_screen(_params):
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.run("rundll32.exe user32.dll,LockWorkStation", shell=True)
        elif system == "Darwin":
            subprocess.run(["pmset", "displaysleepnow"])
        else:
            subprocess.run(["loginctl", "lock-session"])
        return "Locked the laptop screen."
    except Exception as e:
        return f"Couldn't lock screen: {e}"


# The ALLOWLIST. Only these run. No arbitrary shell.
ACTIONS = {
    "open_application": open_application,
    "open_website": open_website,
    "search_web": search_web,
    "system_report": system_report,
    "lock_screen": lock_screen,
}


def run(action, params):
    fn = ACTIONS.get(action)
    if fn is None:
        return f"Unknown or disallowed desktop action: {action}"
    return fn(params or {})


def main():
    if not KEY:
        print("Set JARVIS_API_KEY (and optionally JARVIS_URL) first. See the file header.")
        raise SystemExit(1)
    print(f"[agent] desktop agent online; polling {URL}")
    print(f"[agent] allowed actions: {', '.join(ACTIONS)}")
    backoff = 1
    while True:
        try:
            r = requests.get(f"{URL}/api/desktop/poll", headers=HEADERS, timeout=35)
            backoff = 1
            if r.status_code == 401:
                print("[agent] 401 — JARVIS_API_KEY doesn't match the server. Fix and restart.")
                time.sleep(5); continue
            cmd = r.json()
            if not cmd or not cmd.get("id"):
                continue  # long-poll timed out, just loop
            print(f"[agent] command: {cmd['action']} {cmd.get('args')}")
            output = run(cmd["action"], cmd.get("args"))
            requests.post(f"{URL}/api/desktop/result", headers=HEADERS,
                          json={"command_id": cmd["id"], "output": output}, timeout=10)
            print(f"[agent] -> {output}")
        except requests.exceptions.RequestException as e:
            print(f"[agent] connection issue ({e}); retrying in {backoff}s")
            time.sleep(backoff); backoff = min(backoff * 2, 30)
        except KeyboardInterrupt:
            print("\n[agent] offline."); break
        except Exception as e:
            print(f"[agent] error: {e}"); time.sleep(2)


if __name__ == "__main__":
    main()
