import os
import time
import json
import requests
import textwrap
import usb.core
import usb.util
import argparse
import signal
import sys
import logging
import threading
import gc
try:
    import psutil
except Exception:
    psutil = None
from PIL import Image, ImageDraw, ImageFont
from escpos.printer import Usb

# --- CONFIG (env / CLI overridable) ---
DEFAULT_NTFY_HOST = os.environ.get("NTFY_HOST")
DEFAULT_NTFY_TOPIC = os.environ.get("NTFY_TOPIC")
VENDOR_ID = int(os.environ.get("PRINTER_VENDOR", "0x0fe6"), 16)
PRODUCT_ID = int(os.environ.get("PRINTER_PRODUCT", "0x811e"), 16)
MEM_THRESHOLD_PERCENT = int(os.environ.get("MEM_THRESHOLD_PERCENT", "80"))
MEM_RESUME_PERCENT = int(os.environ.get("MEM_RESUME_PERCENT", "70"))
MAX_MESSAGE_LENGTH = int(os.environ.get("MAX_MESSAGE_LENGTH", "300"))
MAX_LINES = int(os.environ.get("MAX_LINES", "3"))
# global stop event used to exit loops cleanly
STOP_EVENT = threading.Event()
MONITOR = None

class WhiteboardPrinter:
    def __init__(self):
        self.p = None
        self._paused = False
        self.connect()

    def set_paused(self, paused: bool):
        self._paused = bool(paused)

    @property
    def is_paused(self):
        return self._paused

    def connect(self):
        try:
            self.p = Usb(VENDOR_ID, PRODUCT_ID, 0)
            # detach kernel driver if active
            try:
                if self.p.device.is_kernel_driver_active(0):
                    self.p.device.detach_kernel_driver(0)
            except Exception:
                # device/kernel driver info may not be available on some platforms
                logging.debug("Could not check/detach kernel driver")
            print("🟢 Hardware Linked")
        except Exception:
            logging.exception("Failed to connect to USB printer")
            self.p = None

    def create_layout(self, message):
        # We use a narrower width (384) so we can DOUBLE the size on the printer
        width = 384

        # MASSIVE font sizes
        font_main_size = 70
        font_sub_size = 35

        canvas = Image.new('RGB', (width, 1000), color=(255, 255, 255))
        draw = ImageDraw.Draw(canvas)

        try:
            font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_main_size)
            font_reg = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_sub_size)
        except Exception:
            logging.warning("Could not load TTF fonts; falling back to default font")
            font_bold = font_reg = ImageFont.load_default()

        y = 30
        # 1. Lightning Bolt Symbol (Centered)
        draw.text(((width - 40)//2, y), "⚡", font=font_bold, fill=(0, 0, 0))
        y += 90

        # 2. Main Message (Heavy Wrap for Size)
        # enforce message caps to avoid unbounded image sizes
        if len(message) > MAX_MESSAGE_LENGTH:
            message = message[:MAX_MESSAGE_LENGTH-3] + "..."

        lines = textwrap.wrap(message, width=10)[:MAX_LINES] # 10 chars max keeps it huge
        if len(textwrap.wrap(message, width=10)) > MAX_LINES:
            if lines:
                lines[-1] = (lines[-1][:max(0, len(lines[-1]) - 3)] + "...")

        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font_bold)
            draw.text(((width - (bbox[2]-bbox[0]))//2, y), line, font=font_bold, fill=(0, 0, 0))
            y += font_main_size + 10

        # 3. Divider line
        y += 15
        draw.line([20, y, width-20, y], fill=(0, 0, 0), width=3)
        y += 25

        # 4. Date Sub-header
        date_str = time.strftime("%b %d, %Y")
        bbox = draw.textbbox((0, 0), date_str, font=font_reg)
        draw.text(((width - (bbox[2]-bbox[0]))//2, y), date_str, font=font_reg, fill=(0, 0, 0))
        y += 60

        return canvas.crop((0, 0, width, y))

    def print_msg(self, message):
        if self.is_paused:
            logging.warning("Printer paused due to high memory — dropping message")
            return
        if not self.p:
            self.connect()
        try:
            img = self.create_layout(message)
            if not self.p:
                # No printer available; log and skip printing instead of crashing
                logging.warning("No printer connected — skipping print: %s", message)
                return
            self.p.hw("INIT")
            # Scale image for larger output (manual 2x upsampling)
            scaled_width = img.width * 2
            scaled_height = img.height * 2
            img_scaled = img.resize((scaled_width, scaled_height), Image.NEAREST)
            self.p.image(img_scaled, impl="bitImageColumn")
            self.p.text("\n\n\n\n")
            self.p.cut()
            print(f"✅ Printed Big: {message}")
        except Exception as e:
            logging.exception("Printing error")
            # attempt reconnect on any error
            self.connect()
        finally:
            if 'img' in locals():
                try:
                    del img
                except Exception:
                    pass
            if 'img_scaled' in locals():
                try:
                    del img_scaled
                except Exception:
                    pass
            gc.collect()

def listen(ntfy_url):
    global MONITOR
    wp = WhiteboardPrinter()
    logging.info("Listening to %s", ntfy_url)
    # Start memory monitor
    MONITOR = MemoryMonitor(wp)
    MONITOR.start()
    while not STOP_EVENT.is_set():
        try:
            # use context manager to ensure response is closed
            with requests.get(ntfy_url, stream=True, timeout=None) as r:
                r.raise_for_status()
                for line in r.iter_lines(decode_unicode=True):
                    if STOP_EVENT.is_set():
                        break
                    if line:
                        try:
                            payload = json.loads(line)
                        except Exception:
                            logging.warning("Received non-json line: %s", line)
                            continue
                        msg = payload.get("message", "")
                        if msg:
                            # enforce a local truncation/caps before printing
                            if len(msg) > MAX_MESSAGE_LENGTH:
                                msg = msg[:MAX_MESSAGE_LENGTH-3] + "..."
                            wp.print_msg(msg)
        except Exception:
            if STOP_EVENT.is_set():
                break
            logging.exception("Connection to ntfy failed — retrying in 5s")
            time.sleep(5)
    # stop monitor on exit
    try:
        if MONITOR:
            MONITOR.stop()
            MONITOR.join(timeout=2.0)
    except Exception:
        logging.debug("Error stopping monitor")


class MemoryMonitor(threading.Thread):
    """Background thread checking memory usage and pausing printing when high.

    If memory usage rises above MEM_THRESHOLD_PERCENT, printing is paused until
    usage drops below MEM_RESUME_PERCENT.
    """
    def __init__(self, printer: WhiteboardPrinter, interval: float = 5.0):
        super().__init__(daemon=True)
        self.printer = printer
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            try:
                used_percent = self._get_mem_percent()
                if used_percent is None:
                    # Unable to determine memory usage; skip
                    time.sleep(self.interval)
                    continue
                if used_percent >= MEM_THRESHOLD_PERCENT and not self.printer.is_paused:
                    logging.warning("Memory usage high (%.1f%%) — pausing printer", used_percent)
                    self.printer.set_paused(True)
                elif used_percent <= MEM_RESUME_PERCENT and self.printer.is_paused:
                    logging.info("Memory usage normal (%.1f%%) — resuming printer", used_percent)
                    self.printer.set_paused(False)
            except Exception:
                logging.exception("Memory monitor error")
            time.sleep(self.interval)

    def stop(self):
        self._stop_event.set()

    def _get_mem_percent(self):
        try:
            if psutil:
                return psutil.virtual_memory().percent
            # fallback: read /proc/meminfo
            with open('/proc/meminfo', 'r') as f:
                info = f.read()
            mem_total = None
            mem_available = None
            for line in info.splitlines():
                if line.startswith('MemTotal:'):
                    mem_total = int(line.split()[1])
                elif line.startswith('MemAvailable:'):
                    mem_available = int(line.split()[1])
            if mem_total and mem_available:
                used = mem_total - mem_available
                return used / mem_total * 100.0
        except Exception:
            logging.exception("Failed to read memory usage")
        return None


def shutdown(signum, frame):
    logging.info("Shutting down (signal %s)", signum)
    # signal listen loop and monitor to stop
    try:
        STOP_EVENT.set()
        if MONITOR:
            MONITOR.stop()
            MONITOR.join(timeout=2.0)
    except Exception:
        logging.debug("Error during shutdown cleanup")
    sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Receipt printer listening to an ntfy topic")
    parser.add_argument("--host", default=DEFAULT_NTFY_HOST, help="ntfy host (including scheme)")
    parser.add_argument("--topic", default=DEFAULT_NTFY_TOPIC, help="ntfy topic name")
    args = parser.parse_args()

    if not args.host or not args.topic:
        logging.error("NTFY host/topic not provided. Set NTFY_HOST and NTFY_TOPIC in environment or pass --host/--topic.")
        logging.error("Copy .env.template to .env and fill in NTFY_HOST/NTFY_TOPIC before running.")
        sys.exit(2)

    ntfy_url = f"{args.host.rstrip('/')}/{args.topic}/json"

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    listen(ntfy_url)


if __name__ == "__main__":
    main()