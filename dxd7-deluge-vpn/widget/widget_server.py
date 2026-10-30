#!/usr/bin/env python3
"""Home-screen widget server for DelugeVPN (umbrelOS widgets).

Umbrel fetches JSON from http://widget-server:3000/widgets/<name> every few
seconds and draws it on the home screen. This script gets the torrent list from
Deluge's daemon (port 58846) using the client library that ships inside the
binhex image, logging in with the daemon's own credentials from /config/auth.
No password is stored anywhere.

Never crashes on bad data: if Deluge isn't ready it returns a placeholder widget
and logs why.
"""
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST = os.environ.get("DELUGE_HOST", "localhost")
DAEMON_PORT = int(os.environ.get("DELUGE_DAEMON_PORT", "58846"))
AUTH_FILE = os.environ.get("DELUGE_AUTH_FILE", "/config/auth")
HTTP_PORT = int(os.environ.get("WIDGET_PORT", "3000"))
LIST_LIMIT = int(os.environ.get("WIDGET_LIST_LIMIT", "3"))
SHOW_NAMES = os.environ.get("WIDGET_SHOW_NAMES", "yes").strip().lower() != "no"
FETCH_TIMEOUT = 6.0
REFRESH = os.environ.get("WIDGET_REFRESH", "5s")  # Umbrel's own widget servers send this in every response
POLL_INTERVAL = float(os.environ.get("WIDGET_POLL_SECONDS", "3"))
STALE_AFTER = 20.0   # seconds before saved data is considered too old to show
KEYS = ["name", "state", "progress", "download_payload_rate", "upload_payload_rate"]

STAT_LABELS = ["Downloading", "Seeding", "Paused", "Queued"]
STATE_ORDER = {"Downloading": 0, "Checking": 1, "Allocating": 1, "Moving": 1,
               "Seeding": 2, "Queued": 3, "Paused": 4, "Error": 5}


class WidgetError(Exception):
    pass


# ---------------------------------------------------------------- formatting

def plural(n):
    return "torrent" if n == 1 else "torrents"


def as_float(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def fmt_rate(bytes_per_second):
    """Bytes/s -> '4.4Mbps' / '827Kbps' like the Transmission widget."""
    bps = max(0.0, as_float(bytes_per_second)) * 8
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f}Mbps"
    if bps >= 1_000:
        return f"{round(bps / 1_000)}Kbps"
    return "0Mbps"


def short(text, limit=60):
    text = str(text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "\u2026"


def stats_widget(torrents=None, note="waiting for Deluge"):
    if torrents is None:
        items = [{"title": label, "text": "-", "subtext": note} for label in STAT_LABELS]
    else:
        counts = dict.fromkeys(STAT_LABELS, 0)
        for t in torrents.values():
            state = t.get("state")
            if state in counts:
                counts[state] += 1
        items = [{"title": label, "text": str(counts[label]), "subtext": plural(counts[label])}
                 for label in STAT_LABELS]
    return {"type": "four-stats", "refresh": REFRESH, "items": items}


def list_widget(torrents=None, note="Waiting for Deluge...", limit=LIST_LIMIT, show_names=SHOW_NAMES):
    if torrents is None:
        return {"type": "list", "refresh": REFRESH, "items": [], "noItemsText": note}

    def sort_key(t):
        return (STATE_ORDER.get(t.get("state"), 6),
                -as_float(t.get("download_payload_rate")),
                -as_float(t.get("upload_payload_rate")),
                str(t.get("name") or ""))

    items = []
    for t in sorted(torrents.values(), key=sort_key)[:limit]:
        percent = min(100, int(as_float(t.get("progress"))))
        name = (short(t.get("name")) or "Unnamed torrent") if show_names else "Torrent"
        items.append({
            "text": f"{percent}% \u2022 {name}",
            "subtext": f"\u2193{fmt_rate(t.get('download_payload_rate'))} "
                       f"\u2191{fmt_rate(t.get('upload_payload_rate'))}",
        })
    return {"type": "list", "refresh": REFRESH, "items": items, "noItemsText": "No torrents"}


# ------------------------------------------------------------ Deluge access

class BrokenSource:
    """Used when Deluge's client library can't be loaded at all."""

    def __init__(self, message):
        self.message = message

    def fetch(self):
        raise WidgetError(self.message)


class DelugeSource:
    """Talks to the Deluge daemon with the client library from the binhex image.

    The library is built on Twisted, so the Twisted reactor runs in a background
    thread and the plain HTTP server below hands requests over to it.
    """

    def __init__(self):
        from twisted.internet import defer, reactor
        from deluge.ui.client import client

        self.defer, self.reactor, self.client = defer, reactor, client
        self.lock = defer.DeferredLock()
        self.connected = False
        threading.Thread(target=lambda: reactor.run(installSignalHandlers=False),
                         daemon=True).start()

    def _credentials(self):
        try:
            with open(AUTH_FILE, encoding="utf-8") as fh:
                lines = [ln.strip().split(":") for ln in fh if ln.strip() and not ln.startswith("#")]
        except OSError as exc:
            raise WidgetError(f"cannot read {AUTH_FILE} yet ({exc.__class__.__name__})") from exc
        entries = [p for p in lines if len(p) >= 2]
        for parts in entries:
            if parts[0] == "localclient":
                return parts[0], parts[1]
        if entries:
            return entries[0][0], entries[0][1]
        raise WidgetError(f"no credentials found in {AUTH_FILE}")

    def _query(self):
        client = self.client

        def connect():
            if self.connected:
                return self.defer.succeed(None)
            user, password = self._credentials()
            deferred = client.connect(HOST, DAEMON_PORT, user, password)

            def done(_):
                self.connected = True
            return deferred.addCallback(done)

        def reset(failure):
            self.connected = False
            try:
                client.disconnect()
            except Exception:  # noqa: BLE001 - already gone is fine
                pass
            return failure

        deferred = connect()
        deferred.addCallback(lambda _: client.core.get_torrents_status({}, KEYS))
        deferred.addErrback(reset)
        return deferred

    def fetch(self):
        outcome, done = {}, threading.Event()

        def run():
            try:
                deferred = self.lock.run(self._query)
            except Exception as exc:  # noqa: BLE001 - e.g. credentials unreadable
                outcome["err"] = str(exc) or exc.__class__.__name__
                done.set()
                return

            def ok(result):
                outcome["ok"] = result
                done.set()

            def bad(failure):
                outcome["err"] = failure.getErrorMessage() or failure.type.__name__
                done.set()
            deferred.addCallbacks(ok, bad)

        self.reactor.callFromThread(run)
        if not done.wait(FETCH_TIMEOUT):
            raise WidgetError("timed out talking to the Deluge daemon")
        if "err" in outcome:
            raise WidgetError(outcome["err"])
        return outcome["ok"] or {}


# --------------------------------------------------------------------- HTTP

_last_log = {"msg": None, "at": 0.0}


def log(message):
    sys.stderr.write(f"[dxd7-widget] {message}\n")
    sys.stderr.flush()


def log_problem(message):
    """Log a problem when it changes, or once a minute while it persists."""
    now = time.time()
    if message != _last_log["msg"] or now - _last_log["at"] > 60:
        log(message)
        _last_log.update(msg=message, at=now)


class Poller(threading.Thread):
    """Asks Deluge for the torrent list every few seconds and keeps the latest
    answer, so HTTP requests from Umbrel are answered instantly and never wait
    on Deluge (a slow or failing connection can't make the widget time out)."""

    def __init__(self, source):
        super().__init__(daemon=True)
        self.source = source
        self.lock = threading.Lock()
        self.data = None
        self.updated = 0.0
        self.healthy = False

    def poll_once(self):
        try:
            data = self.source.fetch()
        except WidgetError as exc:
            hint = "" if isinstance(self.source, BrokenSource) else (
                ". If this keeps happening, make sure Deluge is running and "
                "'Allow Remote Connections' is ticked in Deluge > Preferences > Daemon.")
            self._failed(f"{exc}{hint}")
        except Exception as exc:  # noqa: BLE001 - never let the poller die
            self._failed(f"unexpected error: {exc.__class__.__name__}: {exc}")
        else:
            with self.lock:
                self.data, self.updated = data, time.time()
            if not self.healthy:
                log(f"connected to Deluge ({len(data)} torrents)")
            self.healthy = True
            _last_log["msg"] = None

    def _failed(self, message):
        self.healthy = False
        log_problem(message)

    def run(self):
        while True:
            self.poll_once()
            time.sleep(POLL_INTERVAL)

    def snapshot(self):
        with self.lock:
            if self.data is not None and time.time() - self.updated <= STALE_AFTER:
                return self.data
        return None


ROUTES = {
    "/widgets/torrents": stats_widget,
    "/widgets/active": list_widget,
}


def make_handler(poller):
    seen = set()

    class Handler(BaseHTTPRequestHandler):
        server_version = "dxd7-widget"

        def log_message(self, fmt, *args):  # keep the container log quiet
            pass

        def _send(self, payload, status=200):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?", 1)[0].rstrip("/") or "/"
            if path == "/healthz":
                self._send({"ok": True, "deluge": poller.healthy})
                return
            build = ROUTES.get(path)
            if build is None:
                self._send({"error": "unknown widget"}, 404)
                return
            if path not in seen:
                seen.add(path)
                log(f"first request for {path} from {self.client_address[0]}")
            self._send(build(poller.snapshot()))

    return Handler


def main():
    try:
        source = DelugeSource()
    except Exception as exc:  # noqa: BLE001
        source = BrokenSource(f"cannot load Deluge's client library: {exc.__class__.__name__}: {exc}")
    poller = Poller(source)
    poller.start()
    server = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), make_handler(poller))
    log(f"serving widgets on port {HTTP_PORT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
