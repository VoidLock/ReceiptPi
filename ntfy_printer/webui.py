"""Web UI for ReceiptPi.

A small, self-contained Flask app that runs alongside the ntfy listener and
lets you, from any browser on the network:

  * watch live printer/service status
  * edit every .env-backed setting (with most geometry/image knobs applying
    instantly, no restart required)
  * visually calibrate paper offsets with a live preview image
  * customize priority symbols/banner colors and kanban icon sets
  * browse/search the 1500+ tag emoji map and add custom overrides
  * fire off test prints without needing a real ntfy message

Nothing here is required for the core printer service to work — it's an
optional control surface. It is disabled by default (WEB_UI_ENABLED=false)
and, if enabled without WEB_UI_USERNAME/WEB_UI_PASSWORD, serves an
unauthenticated warning banner on every page since it can trigger physical
prints and rewrite the .env file.
"""

import io
import json
import logging
import os
import threading
from collections import deque
from functools import wraps

from flask import Flask, Response, jsonify, redirect, render_template, request, send_file, url_for
from PIL import ImageEnhance, ImageOps
from dotenv import dotenv_values, set_key

from . import config
from . import settings_store
from .helpers import detect_priority, strip_emojis
from .printer import WhiteboardPrinter

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")

_render_lock = threading.Lock()

# (env key, display label, input type, form group, extra kwargs)
ENV_FIELDS = [
    dict(key="NTFY_HOST", label="ntfy Host", type="text", group="Connection", help="e.g. https://ntfy.sh"),
    dict(key="NTFY_TOPIC", label="ntfy Topic", type="text", group="Connection"),
    dict(key="ERROR_NTFY_TOPIC", label="Error Notification Topic", type="text", group="Connection",
         help="Separate topic that receives failure alerts from this device"),

    dict(key="PRINTER_VENDOR", label="USB Vendor ID", type="text", group="Printer", help="hex, e.g. 0x0fe6"),
    dict(key="PRINTER_PRODUCT", label="USB Product ID", type="text", group="Printer", help="hex, e.g. 0x811e"),
    dict(key="PRINTER_PROFILE", label="Printer Profile", type="text", group="Printer", help="optional, e.g. TM-T20"),

    dict(key="PAPER_WIDTH_MM", label="Paper Width (mm)", type="number", group="Geometry", live=True),
    dict(key="X_OFFSET_MM", label="X Offset (mm)", type="number", step="0.5", group="Geometry", live=True),
    dict(key="Y_OFFSET_MM", label="Y Offset (mm)", type="number", step="0.5", group="Geometry", live=True),
    dict(key="SAFE_MARGIN_MM", label="Safe Margin (mm)", type="number", step="0.5", group="Geometry", live=True),
    dict(key="MAX_HEIGHT_MM", label="Max Receipt Height (mm)", type="number", group="Geometry", live=True,
         help="blank = unlimited"),

    dict(key="IMAGE_SCALE", label="Image Scale", type="number", group="Image", live=True),
    dict(key="IMAGE_CONTRAST", label="Image Contrast", type="number", step="0.1", group="Image", live=True),
    dict(key="IMAGE_IMPL", label="Image Implementation", type="text", group="Image", live=True),
    dict(key="IMAGE_IMPLS", label="Image Implementation Fallbacks", type="text", group="Image", live=True,
         help="comma-separated, tried in order"),

    dict(key="COUNTRY_CODE", label="Country Code", type="text", group="Phone QR", live=True),
    dict(key="PHONE_QR_ENABLED", label="Enable Phone QR Codes", type="checkbox", group="Phone QR", live=True),
    dict(key="PHONE_CALL_KEYWORDS", label="Call Keywords", type="text", group="Phone QR", live=True),
    dict(key="PHONE_TEXT_KEYWORDS", label="Text Keywords", type="text", group="Phone QR", live=True),

    dict(key="MAX_MESSAGE_LENGTH", label="Max Message Length", type="number", group="Messages", live=True),

    dict(key="MEM_THRESHOLD_PERCENT", label="Pause Threshold %", type="number", group="Memory", live=True),
    dict(key="MEM_RESUME_PERCENT", label="Resume Threshold %", type="number", group="Memory", live=True),

    dict(key="LOG_LEVEL", label="Log Level", type="select",
         options=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], group="Logging", live=True),
    dict(key="LOG_FILE", label="Log File Path", type="text", group="Logging"),

    dict(key="AUTO_UPDATE", label="Enable Auto-Update", type="checkbox", group="Auto-Update"),
    dict(key="UPDATE_CHECK_INTERVAL", label="Update Check Interval (s)", type="number", group="Auto-Update"),
    dict(key="GITHUB_REPO", label="GitHub Repo", type="text", group="Auto-Update"),

    dict(key="WEB_UI_ENABLED", label="Enable Web UI", type="checkbox", group="Web UI",
         help="restart required"),
    dict(key="WEB_UI_HOST", label="Web UI Bind Host", type="text", group="Web UI", help="restart required"),
    dict(key="WEB_UI_PORT", label="Web UI Port", type="number", group="Web UI", help="restart required"),
    dict(key="WEB_UI_USERNAME", label="Web UI Username", type="text", group="Web UI",
         help="leave blank to disable auth (not recommended)"),
    dict(key="WEB_UI_PASSWORD", label="Web UI Password", type="password", group="Web UI"),
]

# env key -> (config attribute, caster) for settings that can be applied live,
# in-process, without a service restart.
_LIVE_APPLY = {
    "PAPER_WIDTH_MM": ("PAPER_WIDTH_MM", float),
    "X_OFFSET_MM": ("X_OFFSET_MM", float),
    "Y_OFFSET_MM": ("Y_OFFSET_MM", float),
    "SAFE_MARGIN_MM": ("SAFE_MARGIN_MM", float),
    "MAX_HEIGHT_MM": ("MAX_HEIGHT_MM", lambda v: float(v) if v else None),
    "IMAGE_SCALE": ("IMAGE_SCALE", int),
    "IMAGE_CONTRAST": ("IMAGE_CONTRAST", float),
    "IMAGE_IMPL": ("IMAGE_IMPL", str),
    "IMAGE_IMPLS": ("IMAGE_IMPLS", str),
    "COUNTRY_CODE": ("COUNTRY_CODE", str),
    "PHONE_QR_ENABLED": ("PHONE_QR_ENABLED", lambda v: str(v).lower() == "true"),
    "PHONE_CALL_KEYWORDS": ("PHONE_CALL_KEYWORDS", lambda v: [k.strip().upper() for k in v.split(",") if k.strip()]),
    "PHONE_TEXT_KEYWORDS": ("PHONE_TEXT_KEYWORDS", lambda v: [k.strip().upper() for k in v.split(",") if k.strip()]),
    "MAX_MESSAGE_LENGTH": ("MAX_MESSAGE_LENGTH", int),
    "MEM_THRESHOLD_PERCENT": ("MEM_THRESHOLD_PERCENT", int),
    "MEM_RESUME_PERCENT": ("MEM_RESUME_PERCENT", int),
    "LOG_LEVEL": ("LOG_LEVEL", str),
}

_GEOMETRY_KEYS = {"PAPER_WIDTH_MM", "SAFE_MARGIN_MM"}


def _recompute_derived_geometry():
    config.PAPER_WIDTH_PX = int(round(config.PAPER_WIDTH_MM / 25.4 * config.PRINTER_DPI))
    config.SAFE_MARGIN_PX = int(round(config.SAFE_MARGIN_MM / 25.4 * config.PRINTER_DPI))
    config.MAX_PRINTABLE_WIDTH_PX = config.PAPER_WIDTH_PX - (2 * config.SAFE_MARGIN_PX)


def _apply_env_to_config(key, value):
    """Best-effort live-apply of a single .env key onto the running config module."""
    if key not in _LIVE_APPLY:
        return
    attr, caster = _LIVE_APPLY[key]
    try:
        setattr(config, attr, caster(value))
    except Exception:
        logging.exception("Web UI: failed to live-apply %s=%r", key, value)
        return
    if key in _GEOMETRY_KEYS:
        _recompute_derived_geometry()


def _current_env_values():
    """Values as currently written in .env, falling back to live config where absent."""
    on_disk = dotenv_values(ENV_PATH) if os.path.exists(ENV_PATH) else {}
    values = {}
    for field in ENV_FIELDS:
        key = field["key"]
        if key in on_disk and on_disk[key] is not None:
            values[key] = on_disk[key]
        else:
            values[key] = str(getattr(config, key, ""))
    return values


def _hex_to_rgb(hex_color, fallback=(200, 200, 200)):
    try:
        hex_color = hex_color.lstrip("#")
        return [int(hex_color[i:i + 2], 16) for i in (0, 2, 4)]
    except Exception:
        return list(fallback)


def _rgb_to_hex(rgb):
    try:
        r, g, b = rgb[0], rgb[1], rgb[2]
        return "#{:02x}{:02x}{:02x}".format(int(r), int(g), int(b))
    except Exception:
        return "#c8c8c8"


def _tail_lines(path, n=200):
    if not path or not os.path.exists(path):
        return []
    try:
        with open(path, "r", errors="replace") as f:
            return list(deque(f, maxlen=n))
    except Exception:
        logging.exception("Web UI: failed to read log file %s", path)
        return []


def create_app(printer=None):
    """Build the Flask app. `printer` is an existing WhiteboardPrinter to share
    with the ntfy listener thread (may be None, e.g. for standalone testing)."""
    app = Flask(__name__)
    app.secret_key = os.urandom(24)
    settings_store.load()

    def _authorized():
        if not config.WEB_UI_USERNAME:
            return True
        auth = request.authorization
        return bool(
            auth and auth.username == config.WEB_UI_USERNAME and auth.password == config.WEB_UI_PASSWORD
        )

    def requires_auth(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not _authorized():
                return Response(
                    "Authentication required.",
                    401,
                    {"WWW-Authenticate": 'Basic realm="ReceiptPi"'},
                )
            return view(*args, **kwargs)
        return wrapped

    def _printer_status():
        mem_percent = None
        try:
            import psutil
            mem_percent = round(psutil.virtual_memory().percent, 1)
        except Exception:
            pass
        return {
            "have_printer": printer is not None,
            "preview_mode": bool(printer and printer.preview_mode),
            "connected": bool(printer and not printer.preview_mode and printer.p is not None),
            "paused": bool(printer and printer.is_paused),
            "ntfy_host": config.DEFAULT_NTFY_HOST or "",
            "ntfy_topic": config.DEFAULT_NTFY_TOPIC or "",
            "auto_update": config.AUTO_UPDATE,
            "mem_percent": mem_percent,
            "auth_enabled": bool(config.WEB_UI_USERNAME),
            "version": __import__("ntfy_printer").__version__,
        }

    # ------------------------------------------------------------------ #
    # Dashboard
    # ------------------------------------------------------------------ #
    @app.route("/")
    @requires_auth
    def dashboard():
        return render_template("dashboard.html", status=_printer_status(), active="dashboard")

    @app.route("/api/status")
    @requires_auth
    def api_status():
        return jsonify(_printer_status())

    # ------------------------------------------------------------------ #
    # Config editor
    # ------------------------------------------------------------------ #
    @app.route("/config", methods=["GET", "POST"])
    @requires_auth
    def config_editor():
        message = None
        if request.method == "POST":
            for field in ENV_FIELDS:
                key = field["key"]
                if field["type"] == "checkbox":
                    value = "true" if request.form.get(key) == "on" else "false"
                else:
                    value = request.form.get(key, "").strip()
                    if field["type"] == "password" and value == "":
                        # Don't clobber an existing password with a blank field.
                        current = dotenv_values(ENV_PATH).get(key) if os.path.exists(ENV_PATH) else None
                        if current:
                            continue
                try:
                    set_key(ENV_PATH, key, value, quote_mode="never")
                except Exception:
                    logging.exception("Web UI: failed to write %s to .env", key)
                _apply_env_to_config(key, value)
            message = "Settings saved. Geometry, image, phone-QR, memory, and log-level " \
                      "changes are already live. Connection/printer/web-UI changes need a restart."

        values = _current_env_values()
        groups = {}
        for field in ENV_FIELDS:
            groups.setdefault(field["group"], []).append({**field, "value": values.get(field["key"], "")})
        group_order = ["Connection", "Printer", "Geometry", "Image", "Phone QR",
                       "Messages", "Memory", "Logging", "Auto-Update", "Web UI"]
        ordered_groups = [(g, groups[g]) for g in group_order if g in groups]
        return render_template("config.html", groups=ordered_groups, message=message, active="config")

    # ------------------------------------------------------------------ #
    # Visual calibration
    # ------------------------------------------------------------------ #
    @app.route("/calibration")
    @requires_auth
    def calibration_page():
        return render_template("calibration.html", config=config, active="calibration",
                                have_printer=printer is not None and not printer.preview_mode)

    @app.route("/calibration/preview.png")
    @requires_auth
    def calibration_preview():
        kind = request.args.get("kind", "grid")
        overrides = {}
        for param, attr, caster in [
            ("x_offset", "X_OFFSET_MM", float),
            ("y_offset", "Y_OFFSET_MM", float),
            ("safe_margin", "SAFE_MARGIN_MM", float),
            ("paper_width", "PAPER_WIDTH_MM", float),
        ]:
            raw = request.args.get(param)
            if raw not in (None, ""):
                try:
                    overrides[attr] = caster(raw)
                except ValueError:
                    pass

        lock = printer.print_lock if printer else _render_lock
        with lock:
            saved = {attr: getattr(config, attr) for attr in overrides}
            try:
                for attr, val in overrides.items():
                    setattr(config, attr, val)
                if overrides:
                    _recompute_derived_geometry()
                render_printer = printer or WhiteboardPrinter(preview_mode=True)
                img = (render_printer.create_calibration_grid() if kind == "grid"
                       else render_printer.create_alignment_test())
                img_mono = img.convert("L")
                img_mono = ImageOps.autocontrast(img_mono)
                img_mono = ImageEnhance.Contrast(img_mono).enhance(config.IMAGE_CONTRAST)
            finally:
                for attr, val in saved.items():
                    setattr(config, attr, val)
                if overrides:
                    _recompute_derived_geometry()

        buf = io.BytesIO()
        img_mono.save(buf, format="PNG")
        buf.seek(0)
        resp = send_file(buf, mimetype="image/png")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.route("/calibration/apply", methods=["POST"])
    @requires_auth
    def calibration_apply():
        for field, attr in [("x_offset", "X_OFFSET_MM"), ("y_offset", "Y_OFFSET_MM"),
                             ("safe_margin", "SAFE_MARGIN_MM"), ("paper_width", "PAPER_WIDTH_MM"),
                             ("max_height", "MAX_HEIGHT_MM")]:
            raw = request.form.get(field, "").strip()
            if attr == "MAX_HEIGHT_MM" and raw == "":
                set_key(ENV_PATH, attr, "", quote_mode="never")
                config.MAX_HEIGHT_MM = None
                continue
            if raw == "":
                continue
            set_key(ENV_PATH, attr, raw, quote_mode="never")
            _apply_env_to_config(attr, raw)
        return jsonify({"ok": True})

    @app.route("/calibration/print", methods=["POST"])
    @requires_auth
    def calibration_print():
        if not printer or printer.preview_mode:
            return jsonify({"ok": False, "error": "No physical printer available (preview mode)."}), 400
        kind = request.form.get("kind", "grid")
        with printer.print_lock:
            if not printer.is_ready():
                printer.connect()
            if not printer.is_ready():
                return jsonify({"ok": False, "error": "Printer not ready — check the USB connection."}), 503
            try:
                img = (printer.create_calibration_grid() if kind == "grid"
                       else printer.create_alignment_test())
                img_mono = img.convert("L")
                img_mono = ImageOps.autocontrast(img_mono)
                img_mono = ImageEnhance.Contrast(img_mono).enhance(config.IMAGE_CONTRAST)
                img_mono = img_mono.convert("1")
                impls = ([i.strip() for i in config.IMAGE_IMPLS.split(",") if i.strip()]
                         if config.IMAGE_IMPLS else [config.IMAGE_IMPL])
                for impl in impls:
                    try:
                        printer.p.image(img_mono, impl=impl)
                        break
                    except TypeError:
                        printer.p.image(img_mono)
                        break
                printer.p.text("\n\n\n\n")
                printer.p.cut()
                return jsonify({"ok": True})
            except Exception as e:
                logging.exception("Web UI: calibration print failed")
                return jsonify({"ok": False, "error": str(e)}), 500

    # ------------------------------------------------------------------ #
    # Priority symbols / banner styles / kanban icons
    # ------------------------------------------------------------------ #
    @app.route("/priority", methods=["GET", "POST"])
    @requires_auth
    def priority_page():
        error = None
        if request.method == "POST":
            data = settings_store.current()
            try:
                for level in ("max", "high", "default", "low", "min"):
                    data["priority_symbols"][level] = {
                        "symbol": request.form.get(f"sym_symbol_{level}", "⚡").strip() or "⚡",
                        "count": max(1, min(9, int(request.form.get(f"sym_count_{level}", 1) or 1))),
                    }
                for level in ("critical", "high", "medium", "low"):
                    data["priority_banner_styles"][level] = {
                        "text": request.form.get(f"banner_text_{level}", level.upper()).strip() or level.upper(),
                        "fill": _hex_to_rgb(request.form.get(f"banner_color_{level}", "#c8c8c8")),
                        "pattern": request.form.get(f"banner_pattern_{level}", "light"),
                    }
                    data["icon_priority"][level] = request.form.get(f"icon_priority_{level}", "[!]").strip() or "[!]"

                icon_status_raw = request.form.get("icon_status_json", "").strip()
                if icon_status_raw:
                    data["icon_status"] = json.loads(icon_status_raw)
                icon_type_raw = request.form.get("icon_type_json", "").strip()
                if icon_type_raw:
                    data["icon_type"] = json.loads(icon_type_raw)

                settings_store.save(data)
            except (ValueError, json.JSONDecodeError) as e:
                error = f"Could not save — check your input: {e}"

        current = settings_store.current()
        banner_colors = {k: _rgb_to_hex(v["fill"]) for k, v in current["priority_banner_styles"].items()}
        return render_template(
            "priority.html",
            current=current,
            banner_colors=banner_colors,
            icon_status_json=json.dumps(current["icon_status"], indent=2, ensure_ascii=False),
            icon_type_json=json.dumps(current["icon_type"], indent=2, ensure_ascii=False),
            error=error,
            active="priority",
        )

    # ------------------------------------------------------------------ #
    # Emoji tag browser + overrides + ascii fallback map
    # ------------------------------------------------------------------ #
    @app.route("/emoji")
    @requires_auth
    def emoji_page():
        current = settings_store.current()
        return render_template(
            "emoji.html",
            overrides=current["tag_emoji_overrides"],
            ascii_map=current["emoji_map"],
            active="emoji",
        )

    @app.route("/api/emoji-tags.json")
    @requires_auth
    def emoji_tags_json():
        from .emoji_map import EMOJI_TAG_MAP
        return jsonify(EMOJI_TAG_MAP)

    @app.route("/emoji/tag-override", methods=["POST"])
    @requires_auth
    def emoji_tag_override_add():
        tag = request.form.get("tag", "").strip().lower()
        emoji = request.form.get("emoji", "").strip()
        if tag and emoji:
            data = settings_store.current()
            data["tag_emoji_overrides"][tag] = emoji
            settings_store.save(data)
        return redirect(url_for("emoji_page"))

    @app.route("/emoji/tag-override/delete", methods=["POST"])
    @requires_auth
    def emoji_tag_override_delete():
        tag = request.form.get("tag", "").strip().lower()
        data = settings_store.current()
        data["tag_emoji_overrides"].pop(tag, None)
        settings_store.save(data)
        return redirect(url_for("emoji_page"))

    @app.route("/emoji/ascii", methods=["POST"])
    @requires_auth
    def emoji_ascii_add():
        emoji = request.form.get("emoji", "").strip()
        replacement = request.form.get("replacement", "").strip()
        if emoji and replacement:
            data = settings_store.current()
            data["emoji_map"][emoji] = replacement
            settings_store.save(data)
        return redirect(url_for("emoji_page"))

    @app.route("/emoji/ascii/delete", methods=["POST"])
    @requires_auth
    def emoji_ascii_delete():
        emoji = request.form.get("emoji", "")
        data = settings_store.current()
        data["emoji_map"].pop(emoji, None)
        settings_store.save(data)
        return redirect(url_for("emoji_page"))

    # ------------------------------------------------------------------ #
    # Test print console
    # ------------------------------------------------------------------ #
    @app.route("/test-print", methods=["GET", "POST"])
    @requires_auth
    def test_print_page():
        result = None
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            message = request.form.get("message", "Test message from the web UI").strip()
            tags = request.form.get("tags", "").strip()
            priority = request.form.get("priority", "3").strip()
            click = request.form.get("click", "").strip()
            via_ntfy = request.form.get("via_ntfy") == "on"

            payload = {"message": message}
            if title:
                payload["title"] = title
            if tags:
                payload["tags"] = tags
            if priority:
                payload["priority"] = priority
            if click:
                payload["click"] = click

            if via_ntfy:
                if not config.DEFAULT_NTFY_HOST or not config.DEFAULT_NTFY_TOPIC:
                    result = {"ok": False, "error": "NTFY_HOST/NTFY_TOPIC not configured."}
                else:
                    import requests
                    ntfy_url = f"{config.DEFAULT_NTFY_HOST.rstrip('/')}/{config.DEFAULT_NTFY_TOPIC}"
                    headers = {}
                    if title:
                        headers["Title"] = title
                    if tags:
                        headers["Tags"] = tags
                    if priority:
                        headers["Priority"] = priority
                    if click:
                        headers["Click"] = click
                    try:
                        requests.post(ntfy_url, data=message.encode("utf-8"), headers=headers, timeout=5)
                        result = {"ok": True, "detail": f"Sent to {ntfy_url} — it'll print via the normal listener."}
                    except Exception as e:
                        result = {"ok": False, "error": str(e)}
            elif not printer:
                result = {"ok": False, "error": "No printer instance available."}
            else:
                try:
                    printer.print_msg(strip_emojis(message), payload=payload)
                    result = {"ok": True, "detail": "Printed directly." if not printer.preview_mode
                              else "Rendered in preview mode (no physical printer attached)."}
                except Exception as e:
                    logging.exception("Web UI: test print failed")
                    result = {"ok": False, "error": str(e)}

        return render_template("test_print.html", result=result, active="test-print")

    # ------------------------------------------------------------------ #
    # Logs
    # ------------------------------------------------------------------ #
    @app.route("/logs")
    @requires_auth
    def logs_page():
        lines = _tail_lines(config.LOG_FILE, 200)
        return render_template("logs.html", lines=lines, log_file=config.LOG_FILE, active="logs")

    return app


class WebUIServer(threading.Thread):
    """Runs the Flask app in its own thread with a cleanly stoppable werkzeug server."""

    def __init__(self, printer=None):
        super().__init__(daemon=True, name="WebUI")
        self.app = create_app(printer)
        from werkzeug.serving import make_server
        self._server = make_server(config.WEB_UI_HOST, config.WEB_UI_PORT, self.app, threaded=True)

    def run(self):
        logging.info("Web UI listening on http://%s:%s", config.WEB_UI_HOST, config.WEB_UI_PORT)
        if not config.WEB_UI_USERNAME:
            logging.warning(
                "Web UI is running WITHOUT authentication (set WEB_UI_USERNAME/WEB_UI_PASSWORD in .env "
                "to secure it)."
            )
        self._server.serve_forever()

    def stop(self):
        self._server.shutdown()


def start_webui(printer=None):
    """Start the web UI in a background thread. Returns the WebUIServer (call .stop() to shut down)."""
    server = WebUIServer(printer)
    server.start()
    return server
