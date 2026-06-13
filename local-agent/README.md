# JARVIS desktop agent (the "hands" node)

Runs on your laptop so your phone can trigger local actions (open apps,
websites, system report, lock screen) — each one approved on your phone
first. The laptop dials OUT to the server and opens no ports.

## Run
```
pip install requests psutil
# Windows PowerShell:
$env:JARVIS_URL="http://localhost:8000"        # or your https ts.net URL
$env:JARVIS_API_KEY="your-api-key-from-.env"
python agent.py
```
Leave it running. You'll see `[agent] desktop agent online`.

## Use (from your phone)
"Jarvis, open Spotify on my computer" → approve on phone → it opens.
"Jarvis, give me a report on my laptop" → approve → CPU/RAM/battery.

## Safety
The agent only runs a fixed allowlist (open_application, open_website,
search_web, system_report, lock_screen). It never runs arbitrary shell
commands. Add new actions consciously in agent.py's ACTIONS dict.
