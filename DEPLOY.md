# Setting up ReceiptPi on a fresh DietPi install

Repo: https://github.com/VoidLock/ReceiptPi

1. **SSH in.** DietPi's default login is `root` / `dietpi` (change the
   password on first login if it prompts you to). Confirm the Pi's IP
   hasn't changed since the reimage (DHCP can reassign it):
   ```bash
   ssh root@<pi-ip>
   ```

2. **Update the OS and install prerequisites:**
   ```bash
   apt update && apt upgrade -y
   apt install -y python3 python3-pip python3-venv git rsync fonts-dejavu-core
   ```
   `fonts-dejavu-core` matters more than it looks — `printer.py` hardcodes paths to
   `/usr/share/fonts/truetype/dejavu/DejaVuSans*.ttf` for all receipt text. If
   those files aren't present, PIL silently falls back to its built-in bitmap
   font, which **ignores every size setting** (font constants, `IMAGE_SCALE`,
   everything) and prints tiny, fixed-size text with no error — just a quiet
   `Could not load TTF fonts; falling back to default font` line in the logs.
   This DietPi image doesn't ship the font by default, so it's an easy miss on
   a fresh install. If text ever looks wrong-sized again, check
   `journalctl -u receipt-printer | grep -i "fallback to default font"` first.

3. **Plug in the thermal printer** (if it isn't already) and confirm the Pi sees it:
   ```bash
   lsusb
   ```
   Note the `idVendor:idProduct` pair on the printer's line (e.g. `0fe6:811e`
   for the Rongta RP850 this project was built against) — you'll need it
   for `.env` in step 5 if it differs from the default.

4. **Clone the repo:**
   ```bash
   cd ~
   git clone https://github.com/VoidLock/ReceiptPi.git
   cd ReceiptPi
   ```

5. **Configure `.env`:**
   ```bash
   cp .env.template .env
   nano .env
   ```
   At minimum set:
   ```bash
   NTFY_HOST=https://ntfy.sh          # or your self-hosted server
   NTFY_TOPIC=<your-topic>            # messages TO print
   PRINTER_VENDOR=0x0fe6              # from lsusb, if different
   PRINTER_PRODUCT=0x811e             # from lsusb, if different

   AUTO_UPDATE=true
   UPDATE_CHECK_INTERVAL=300          # 5 min; a git ls-remote is cheap
   GIT_BRANCH=main
   GITHUB_REPO=VoidLock/ReceiptPi
   ```
   Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X` in nano).

6. **Test it manually before installing as a service** — this catches
   printer/USB issues while you can still see the output directly:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt

   python app.py --calibrate      # prints a grid; check alignment
   python app.py --example text   # prints a sample message
   ```
   Adjust `X_OFFSET_MM` / `SAFE_MARGIN_MM` in `.env` and re-run
   `--calibrate` until it looks right. Ctrl+C to stop.

7. **Install as a systemd service** so it runs on boot and restarts itself:
   ```bash
   chmod +x ./scripts/install_service ./scripts/uninstall_service
   sudo ./scripts/install_service $(whoami)
   ```
   Since you're logged in as `root`, the service will run as `root`,
   which sidesteps any USB-permission (udev) fuss. If you ever install
   this as a non-root user instead and printing fails with a USB
   permission error, that's the fix to look into.

8. **Verify it's running:**
   ```bash
   systemctl status receipt-printer
   journalctl -u receipt-printer -f     # Ctrl+C to stop watching
   ```
   Send a real message to your `NTFY_TOPIC` (e.g. via `curl -d "hello" https://ntfy.sh/<your-topic>`)
   and confirm it prints.

9. **Confirm auto-update is alive** (starts checking ~60s after boot):
   ```bash
   journalctl -u receipt-printer -n 50 --no-pager | grep -i update
   ```
   You should see `Update checker started (interval: 300s, repo: VoidLock/ReceiptPi)`
   and then `Already up to date with main (...)` every 5 minutes.

From here on, updates are just `git push origin main` from your dev
machine — no SSH step needed. See "Normal workflow going forward" below
for how that loop works and how to confirm it end-to-end.

---

# Deploying updates to the Pi (no watcher script needed)

This replaces the old "cron/script that watches for a commit and pulls"
approach. ReceiptPi already ships a background auto-update thread
(`ntfy_printer/updater.py`) that runs *inside* the app's systemd service -
no extra process, no extra cron job. It was just checking GitHub Releases/
Tags, which never fire on a plain `git push` to `main`. It now also checks
the branch directly with `git ls-remote` (a single tiny network call, no
clone/fetch of objects) and pulls when it's behind. That's the whole
mechanism - same near-zero footprint the README already advertises
(<0.5 MB RAM, ~0.1% CPU) since it's one daemon thread waking up once per
`UPDATE_CHECK_INTERVAL`.

## One-time setup on the Pi

1. SSH in:
   ```bash
   ssh <pi-user>@<pi-host-or-ip>
   ```

2. If ReceiptPi is already installed via `scripts/install_service`, it's at
   `/opt/ReceiptPi` and still has its `.git` directory (the installer
   preserves it). Pull this fix in manually once:
   ```bash
   cd /opt/ReceiptPi
   git pull origin main
   ```
   If `git pull` fails with "not a git repository", your install lost its
   `.git` dir (e.g. it was set up from a downloaded zip rather than a
   clone) - see "Recovering a non-git install" below.

3. Edit `/opt/ReceiptPi/.env` and set:
   ```bash
   AUTO_UPDATE=true
   UPDATE_CHECK_INTERVAL=300     # 5 minutes; a git ls-remote is cheap
   GIT_BRANCH=main
   GITHUB_REPO=VoidLock/ReceiptPi   # only matters for the release/tag fallback
   ```
   (300s is a reasonable default for a Pi Zero-class board - it's one
   tiny HTTPS-ish git handshake every 5 minutes, not a persistent
   connection.)

4. Restart the service so it picks up the new code and env:
   ```bash
   sudo systemctl restart receipt-printer
   sudo systemctl status receipt-printer
   journalctl -u receipt-printer -f     # watch it start; Ctrl+C to stop watching
   ```

5. Remove your old watcher (cron entry, standalone script, or systemd
   timer) now that the app handles it:
   ```bash
   crontab -e          # delete the line that polled/pulled the repo, if it's there
   # or, if it was its own systemd unit:
   sudo systemctl disable --now <old-watcher-name>.service
   sudo systemctl disable --now <old-watcher-name>.timer   # if it used a timer
   sudo rm /etc/systemd/system/<old-watcher-name>.*
   sudo systemctl daemon-reload
   ```

## Recovering a non-git install

If `/opt/ReceiptPi` isn't a git repo (no `.git` folder - happens if it was
ever installed from a "Download ZIP" instead of `git clone`), the cheap
`ls-remote` check can't run and auto-update silently falls back to the
GitHub releases/tags API (which needs a tagged release to trigger). Fix it
once:

```bash
sudo systemctl stop receipt-printer
cd /opt
sudo mv ReceiptPi ReceiptPi.bak
sudo git clone https://github.com/VoidLock/ReceiptPi.git ReceiptPi
sudo cp ReceiptPi.bak/.env ReceiptPi/.env
sudo chown -R $(whoami):$(whoami) ReceiptPi
cd ReceiptPi
python3 -m venv venv
venv/bin/pip install -r requirements.txt
sudo systemctl start receipt-printer
```

Then delete `ReceiptPi.bak` once you've confirmed it's running.

## Normal workflow going forward

```bash
# on your dev machine
git add -A
git commit -m "..."
git push origin main
```

Within `UPDATE_CHECK_INTERVAL` seconds the Pi notices the branch moved,
pulls, and restarts itself (`Restart=always` in the systemd unit brings it
right back up). No manual SSH step needed unless you're changing `.env` or
doing a one-time recovery like above.

To force an immediate check instead of waiting, just restart the service
after pushing - the update check runs 60s after each start:
```bash
ssh <pi-user>@<pi-host-or-ip> 'sudo systemctl restart receipt-printer'
```

## Verifying it worked

```bash
journalctl -u receipt-printer -n 50 --no-pager | grep -i update
```

You should see lines like:
```
Update checker started (interval: 300s, repo: <you>/ReceiptPi)
New commit on main: a1b2c3d4 (current: 9f8e7d6c)
Running git pull (branch: main)...
Successfully updated to a1b2c3d4
```
