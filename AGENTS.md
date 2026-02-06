# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

ntfy-receipt-printer is a Python service that subscribes to an [ntfy.sh](https://ntfy.sh) topic and prints incoming messages to a USB thermal receipt printer (ESC/POS compatible). It supports plain text, kanban-style task cards, and priority alert banners.

Target hardware: Orange Pi Zero 2W with 80mm thermal printer (203 DPI).

## Commands

### Running the Service
```bash
# Activate virtual environment first
source venv/bin/activate

# Run in printer mode (requires connected USB printer)
python app.py --host https://ntfy.example.com --topic my-topic

# Run in preview mode (no printer required, opens image windows)
python app.py --preview

# Test with example messages
python app.py --preview --example text
python app.py --preview --example kanban

# Print alignment test pattern
python app.py --test-align
```

### Standalone Preview Tool
```bash
python preview.py "Your message"
python preview.py '{"type":"monday_task","task":"Fix Bug","priority":"high"}'
python preview.py --watch  # Live preview from ntfy stream
```

### Installing as Systemd Service
```bash
chmod +x ./scripts/install_service
chmod +x ./scripts/uninstall_service

sudo ./scripts/install_service $(whoami)
sudo systemctl status receipt-printer
sudo journalctl -u receipt-printer -f
```

### Dependencies
```bash
pip install -r requirements.txt
# System fonts required: sudo apt install fonts-dejavu-core
```

## Architecture

### Core Components

**`app.py`** - Main application:
- `WhiteboardPrinter` class handles USB printer connection and all rendering
- `listen()` function maintains persistent SSE connection to ntfy
- `MemoryMonitor` thread pauses printing when memory usage exceeds threshold
- Signal handlers (`SIGINT`, `SIGTERM`) for graceful shutdown via `STOP_EVENT`

**`preview.py`** - Standalone preview tool with subset of rendering logic for testing without hardware.

### Message Types (via JSON `type` field)

| Type | Description |
|------|-------------|
| Plain text | Default - large centered text with timestamp |
| `text_with_subtext` | Main message + smaller secondary line |
| `priority_alert` | Visual banner (critical/high/medium/low) with hatching patterns |
| `monday_task` | Kanban card with task name, status icons, assignee, due date, optional QR code |

### Key Functions in `app.py`

- `create_layout()` - Renders plain text messages with large fonts
- `render_structured()` - Routes JSON payloads to appropriate template
- `_render_monday_task()` - Kanban card layout with priority bar thickness
- `_render_priority_alert()` - Alert banner with visual priority styling
- `strip_emojis()` - Converts emoji to ASCII (thermal printers don't support Unicode emoji)
- `print_msg()` - Main print entry point with retry logic for USB errors

### Configuration

All settings via environment variables (`.env` file):
- `NTFY_HOST`, `NTFY_TOPIC` - ntfy connection
- `PRINTER_VENDOR`, `PRINTER_PRODUCT` - USB IDs (find with `lsusb`)
- `PAPER_WIDTH_MM` - Paper size (80mm or 58mm)
- `X_OFFSET_MM`, `Y_OFFSET_MM` - Print alignment offsets
- `MEM_THRESHOLD_PERCENT`, `MEM_RESUME_PERCENT` - Memory safeguards

## Testing

Send test messages via curl:
```bash
# Plain text
curl -d "Test Message" https://ntfy.example.com/topic

# Structured JSON
curl -X POST https://ntfy.example.com/topic \
  -H "Content-Type: application/json" \
  -d '{"type":"text_with_subtext","message":"ALERT","subtext":"Check now"}'
```

See `TESTING.md` for comprehensive test commands and troubleshooting.

## Code Patterns

- Pixel calculations use: `int(round(mm / 25.4 * PRINTER_DPI))`
- Safe print margins: 4mm on each side of 80mm paper = 72mm printable
- Image processing pipeline: RGB → scale → grayscale → autocontrast → contrast enhance → 1-bit
- USB retry logic with exponential backoff for transient device errors
