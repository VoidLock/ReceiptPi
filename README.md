Receipt Printer

This small service listens to an ntfy topic and prints incoming messages on a USB ESC/POS thermal printer.

Quick start

1. Install dependencies (use a virtualenv):

```bash
pip install -r requirements.txt
```

2. Run (defaults read from environment or use CLI):

```bash
# using defaults 
python app.py

# override host/topic
python app.py --host https://ntfy.example.com --topic my-topic
```

Environment variables

- `NTFY_HOST` - base ntfy host 
- `NTFY_TOPIC` - default topic 
- `PRINTER_VENDOR` - hex vendor id (default: `0x0fe6`)
- `PRINTER_PRODUCT` - hex product id (default: `0x811e`)

Files changed

- `app.py` — configurable host/topic, better logging, graceful shutdown
- `requirements.txt` — minimal dependencies
- `README.md` — usage notes

Systemd service (run at boot)

A systemd unit template and install helper are included to run the service at boot.

- Template: `deploy/receipt-printer.service.template` (placeholders replaced by the installer)
- Installer script: `scripts/install_service.sh`

Install (run as root or via sudo):

```bash
# from repo root
sudo ./scripts/install_service.sh /path/to/repo myuser
```

The installer writes `/etc/default/receipt-printer` and `/etc/systemd/system/receipt-printer.service`, reloads systemd, enables and starts the service.

Secrets & publishing

- Do NOT commit secrets. Create a local `.env` from `.env.template` and keep it out of git.
- `.env` is listed in `.gitignore` already.

Example (create local .env):

```bash
cp .env.template .env
# Edit .env and fill in your NTFY_HOST and NTFY_TOPIC
```

Prepare a new Git repo and push (example):

```bash
git init
git add .
git commit -m "Initial commit"
# create a remote repository on GitHub then:
git remote add origin git@github.com:youruser/your-repo.git
git branch -M main
git push -u origin main
```

The service installer writes `/etc/default/receipt-printer` (used by systemd); keep secrets there on the target system rather than committing them.
