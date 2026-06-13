# Giving your laptop Jarvis real HTTPS (free, no cloud, no domain)

PWA install and push notifications require HTTPS. Tailscale can issue a real
certificate for your machine's `.ts.net` name — private, free, no domain.

## One-time setup

1. In the Tailscale admin console (login.tailscale.com), open **DNS** and
   enable **MagicDNS** and **HTTPS Certificates** (both are free, off by
   default).

2. On the laptop, with Docker running and Jarvis up on port 8000, run
   (Command Prompt or PowerShell):

   ```
   tailscale serve --bg 8000
   ```

   `--bg` keeps it running in the background. Tailscale fetches a real
   HTTPS cert and starts proxying. It prints your address — something like:

   ```
   https://laptop-vnar78dt.tail821ec9.ts.net/
   ```

3. On your phone (Tailscale on), open that **https://** address.
   Real padlock. The PWA can now install and receive push notifications.

## Make it an installed app
- **Android/Chrome:** menu (⋮) → *Install app* (or *Add to Home screen*).
- **iPhone/Safari:** Share → *Add to Home Screen*.
The icon launches Jarvis fullscreen, no browser bars — a real app.

## Allow notifications
On first load the app asks for notification permission — tap **Allow**.
Now reminders and finished background tasks ring your phone even when the
app is closed (as long as your laptop is on).

## Stop / status
```
tailscale serve status      # see what's being served
tailscale serve --bg 8000 off   # stop serving
```

Note: `http://100.x.y.z:8000` (plain Tailscale IP) still works for quick
chat, but only the https `.ts.net` address supports install + push.
