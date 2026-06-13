# Deploying JARVIS to the cloud — the complete runbook

What you're building: a **second Jarvis** on a small always-on server with a real
`https://` address. Phone reaches it from anywhere — no VPN, no laptop. Your
laptop Jarvis keeps existing; it stays the private node behind Tailscale. The
cloud node starts with **empty memory** (step 8 shows how to carry memories over).

Time: ~45–60 minutes, most of it waiting for accounts and builds.

---

## 1. Get a server (pick ONE)

**Option A — Oracle Cloud "Always Free" (₹0/month).**
Sign up at oracle.com/cloud/free (needs a card for identity verification; it
won't be charged on the Always Free tier). Create an instance:
**Ubuntu 24.04**, shape **VM.Standard.A1.Flex** (the free ARM one — pick
2 OCPUs / 8 GB or whatever it allows). During creation it generates an **SSH
key** — DOWNLOAD the private key file and keep it safe; it's your only way in.
Two Oracle-specific gotchas:
- Free ARM capacity is sometimes "out of stock" in busy regions. If creation
  fails, try again later or pick another region at signup. Be patient.
- Oracle has its OWN firewall in the web console, separate from the server's.
  After creating: **Networking → Virtual Cloud Networks → your VCN → Security
  Lists → Default → Add Ingress Rules** — add two rules, source `0.0.0.0/0`,
  protocol TCP, destination ports **80** and **443**. Skip this and HTTPS will
  never work no matter what you do on the server.

**Option B — Hetzner (~€4/month, just works).**
hetzner.com → Cloud → create a **CX22** server, **Ubuntu 24.04**, set a root
password or SSH key. You get the server's IP instantly. Simpler than Oracle;
costs a coffee per month.

Either way, write down the server's **public IP address**.

## 2. Get a free domain name (DuckDNS)

Caddy needs a domain to issue a real HTTPS certificate. duckdns.org → sign in
with Google/GitHub → type a subdomain (e.g. `pratapjarvis`) → set its IP to
your server's IP → add. You now own `pratapjarvis.duckdns.org` for free.

## 3. Connect to the server

From Windows PowerShell (SSH is built in):

```powershell
# Oracle (key file):
ssh -i C:\path\to\downloaded-key.key ubuntu@YOUR_SERVER_IP
# Hetzner (password):
ssh root@YOUR_SERVER_IP
```

Type `yes` to the first-connection fingerprint question. You're now typing
commands **on the server** — a computer in a datacenter. Everything below
happens there unless said otherwise.

## 4. Send the project to the server

Open a **second PowerShell on your laptop**, from the Desktop folder:

```powershell
scp -r .\jarvis-server ubuntu@YOUR_SERVER_IP:~/
# (Oracle: add  -i C:\path\to\key.key   right after scp)
```

This copies the folder — including your `.env`, which we'll adapt next.
*(Better long-term: push the project to a private GitHub repo and `git clone`
it on the server — your `.gitignore` already keeps `.env` out. Worth doing
soon; scp is fine today.)*

## 5. Prepare the machine (one command)

Back in the **server** window:

```bash
cd ~/jarvis-server
bash deploy/bootstrap.sh
```

Watch it update the system, install Docker, and lock the firewall to ports
22/80/443. When it finishes: type `exit`, then SSH back in (the Docker
permission needs a fresh login).

## 6. Adapt .env and Caddyfile for cloud life

```bash
cd ~/jarvis-server
nano .env
```

(nano basics: arrows to move, edit, then **Ctrl+O Enter** to save, **Ctrl+X** to quit.)
Change/add these lines:

```
API_BIND=127.0.0.1        # CRITICAL: API reachable only through Caddy's HTTPS
NODE_NAME=cloud-1
```

Keep your OpenRouter key. You may set a fresh API_KEY for this node.

```bash
nano Caddyfile
```

Delete the `:80 { ... }` block, uncomment the cloud block, put your real
domain in:

```
pratapjarvis.duckdns.org {
	reverse_proxy api:8000
}
```

## 7. Launch

```bash
docker compose --profile edge up -d --build
```

`--profile edge` adds Caddy (the laptop never needed it; the cloud does).
First build takes several minutes (it bakes the embedding model in). Then:

```bash
docker compose logs -f caddy
```

Watch for `certificate obtained successfully` — that's Caddy talking to Let's
Encrypt and getting your free HTTPS certificate. Ctrl+C exits the logs
(containers keep running — logs are just a window).

**The moment:** on your phone — no Tailscale needed, any network — open
`https://pratapjarvis.duckdns.org`. Padlock. Login page. Claim the owner
account (this server is fresh — first to register owns it, so do it now,
not later). Add to home screen. That icon now works from anywhere on earth,
24/7, laptop off.

## 8. Optional: carry your laptop memories over

On the **laptop** (stack running):

```powershell
docker compose exec postgres pg_dump -U jarvis jarvis > jarvis-backup.sql
scp .\jarvis-backup.sql ubuntu@YOUR_SERVER_IP:~/
```

On the **server**:

```bash
cd ~/jarvis-server
docker compose exec -T postgres psql -U jarvis jarvis < ~/jarvis-backup.sql
docker compose restart api
```

You've just performed a real database backup + restore — the exact mechanism
Phase 6 automates nightly.

## 9. Day-2 operations crib sheet

```bash
docker compose logs -f api        # watch the brain think
docker compose ps                 # what's running
docker compose restart api        # turn it off and on again
docker compose --profile edge up -d --build    # deploy an upgrade
sudo apt-get update && sudo apt-get upgrade -y # monthly: patch the OS
```

Security posture, for your own understanding: the world can reach exactly
three doors — SSH (your key/password), and 80/443 (Caddy, which only proxies
to the API, which demands login, which is rate-limited). The API's own port
is bound to 127.0.0.1 because Docker-published ports bypass UFW — the binding,
not the firewall, is what keeps it private. Postgres and Redis publish no
ports at all; they exist only on Docker's internal network.
