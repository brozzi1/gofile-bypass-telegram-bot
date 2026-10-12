# @title
import os
import sys
import json
import time
import base64
import socket
import shutil
import tempfile
import subprocess
import urllib.request
from urllib.parse import urlsplit
import re

# Install lightweight dependency if needed
try:
    import websocket
except ImportError:
    subprocess.check_call([
        sys.executable, "-m", "pip", "install", "-q", "websocket-client"
    ])
    import websocket


# Reconfigure stdout/stderr for Windows console unicode support
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Cross-platform Chrome finder
def get_chrome():
    if sys.platform == "win32":
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            shutil.which("chrome.exe"),
            shutil.which("chrome"),
        ]
        for c in candidates:
            if c and os.path.exists(c):
                return c

    elif sys.platform == "darwin":
        for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Chromium.app/Contents/MacOS/Chromium"):
            if os.path.exists(p):
                return p

    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        path = shutil.which(name)
        if path:
            return path

    if sys.platform.startswith("linux") and os.geteuid() == 0 if hasattr(os, "geteuid") else False:
        try:
            setup = r"""
            set -e
            apt-get update -qq
            apt-get install -y -qq curl gnupg
            install -d -m 0755 /etc/apt/keyrings
            curl -fsSL https://dl.google.com/linux/linux_signing_key.pub |
              gpg --dearmor --yes -o /etc/apt/keyrings/google-chrome.gpg
            chmod a+r /etc/apt/keyrings/google-chrome.gpg
            echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main" \
              > /etc/apt/sources.list.d/google-chrome.list
            apt-get update -qq
            apt-get install -y -qq google-chrome-stable
            """
            subprocess.run(["bash", "-lc", setup], check=True)
            return shutil.which("google-chrome")
        except Exception:
            pass

    return None


# Lightweight decoder:
# Base64 -> Base64 -> ROT13 -> Base64 -> JSON -> Base64 URL
ROT13 = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
    "NOPQRSTUVWXYZABCDEFGHIJKLMnopqrstuvwxyzabcdefghijklm"
)

def b64decode_text(s):
    s = "".join(str(s).split())
    s += "=" * (-len(s) % 4)
    return base64.b64decode(s, altchars=b"-_").decode("utf-8")


def decode_o(value):
    if isinstance(value, dict):
        value = value.get("value", value.get("o", value))

    if not isinstance(value, str):
        raise ValueError("Unexpected o value")

    value = value.strip()

    # Already decoded
    if value.startswith(("https://", "http://")):
        return value

    first = b64decode_text(value)
    second = b64decode_text(first)
    third = second.translate(ROT13)
    data = json.loads(b64decode_text(third))

    result = data["o"]

    if isinstance(result, dict):
        result = result.get("value", result.get("o"))

    if not isinstance(result, str):
        raise ValueError("Decoded o is not a string")

    result = result.strip()

    if not result.startswith(("https://", "http://")):
        try:
            candidate = b64decode_text(result).strip()
            if candidate.startswith(("https://", "http://")):
                result = candidate
        except Exception:
            pass

    # Handle Markdown-formatted URLs if present
    match = re.fullmatch(r"\[([^\]]+)\]\((https?://[^)]+)\)", result)
    if match:
        result = match.group(2)

    return result


def normalize_url(url):
    url = url.strip().strip("'\"")

    match = re.fullmatch(r"\[[^\]]+\]\((https?://[^)]+)\)", url)
    if match:
        url = match.group(1)

    if not url.startswith(("https://", "http://")):
        url = "https://" + url

    parsed = urlsplit(url)

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Invalid URL")

    return url


def get_json(url):
    with urllib.request.urlopen(url, timeout=2) as response:
        return json.loads(response.read())


# Runs before the website's JavaScript
PRELOAD = r"""
(() => {
  function capture(storage, key, value) {
    if (String(key) === "o") {
      console.info("__O_CAPTURE__" + JSON.stringify({
        storage: storage,
        raw: String(value),
        url: location.href
      }));
    }
  }

  for (const name of ["localStorage", "sessionStorage"]) {
    try {
      const original = window[name];

      const proxy = new Proxy(original, {
        get(target, key) {
          if (key === "setItem") {
            return (k, v) => {
              capture(name, k, v);
              return target.setItem(k, v);
            };
          }

          const value = Reflect.get(target, key, target);
          return typeof value === "function"
            ? value.bind(target) : value;
        },

        set(target, key, value) {
          capture(name, key, value);
          return Reflect.set(target, key, value, target);
        }
      });

      Object.defineProperty(window, name, {
        configurable: true,
        get: () => proxy
      });
    } catch (_) {}
  }
})();
"""


# Read storage and unwrap {"value": "...", "expiry": ...}
READ_STORAGE = r"""
(() => {
  function unwrap(raw) {
    try {
      const obj = JSON.parse(raw);

      if (obj && typeof obj.value === "string")
        return obj.value;

      if (obj && typeof obj.o === "string")
        return obj.o;
    } catch (_) {}

    return raw;
  }

  function findO(obj, depth=0) {
    if (!obj || typeof obj !== "object" || depth > 8)
      return null;

    if (Object.prototype.hasOwnProperty.call(obj, "o"))
      return unwrap(
        typeof obj.o === "string" ? obj.o : JSON.stringify(obj.o)
      );

    for (const value of Object.values(obj)) {
      const result = findO(value, depth + 1);
      if (result !== null) return result;
    }

    return null;
  }

  const diagnostic = {};

  for (const name of ["localStorage", "sessionStorage"]) {
    try {
      const store = window[name];
      const keys = Object.keys(store);
      diagnostic[name] = keys;

      const direct = store.getItem("o");

      if (direct !== null) {
        return {
          found: true,
          value: unwrap(direct),
          url: location.href
        };
      }

      for (const key of keys) {
        try {
          const result = findO(JSON.parse(store.getItem(key)));
          if (result !== null) {
            return {
              found: true,
              value: result,
              url: location.href
            };
          }
        } catch (_) {}
      }
    } catch (e) {
      diagnostic[name] = String(e);
    }
  }

  return {
    found: false,
    url: location.href,
    storage: diagnostic
  };
})()
"""


def unwrap_captured(raw):
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            if isinstance(obj.get("value"), str):
                return obj["value"]
            if isinstance(obj.get("o"), str):
                return obj["o"]
    except (ValueError, TypeError):
        pass
    return raw


def resolve_http_fast(url):
    norm_url = normalize_url(url)
    fetch_url = norm_url
    if "greenmotors.club" in norm_url:
        fetch_url = norm_url.replace("greenmotors.club", "greenmotors.cc")

    req = urllib.request.Request(
        fetch_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        html = resp.read().decode("utf-8", errors="replace")

    patterns = [
        r"s\(\s*['\"]o['\"]\s*,\s*['\"]([^'\"]+)['\"]",
        r"localStorage\.setItem\(\s*['\"]o['\"]\s*,\s*['\"]([^'\"]+)['\"]",
        r"['\"]o['\"]\s*,\s*['\"]([A-Za-z0-9+/=_-]{30,})['\"]",
        r"['\"]?o['\"]?\s*[:=]\s*['\"]([A-Za-z0-9+/=_-]{30,})['\"]",
    ]
    for p in patterns:
        for match in re.findall(p, html):
            try:
                dec = decode_o(match)
                if dec.startswith(("http://", "https://")):
                    return dec
            except Exception:
                continue

    for token in re.findall(r"[A-Za-z0-9+/=_-]{50,}", html):
        try:
            dec = decode_o(token)
            if dec.startswith(("http://", "https://")):
                return dec
        except Exception:
            continue

    raise RuntimeError("HTTP fast extraction failed")


def run_decoder(urls):
    remaining_urls = []
    for u in urls:
        try:
            res = resolve_http_fast(u)
            print(res, flush=True)
        except Exception:
            remaining_urls.append(u)

    if not remaining_urls:
        return
    urls = remaining_urls

    chrome = get_chrome()
    if not chrome:
        raise RuntimeError("Chrome executable not found and fast HTTP resolution failed.")

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    profile = tempfile.TemporaryDirectory(prefix="decoder-")
    proc = None
    ws = None

    try:
        proc = subprocess.Popen(
            [
                chrome,
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-extensions",
                "--no-first-run",
                "--no-default-browser-check",
                "--remote-allow-origins=*",
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile.name}",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        deadline = time.monotonic() + 15

        while time.monotonic() < deadline:
            try:
                get_json(f"http://127.0.0.1:{port}/json/version")
                break
            except Exception:
                if proc.poll() is not None:
                    raise RuntimeError("Chrome failed to start")
                time.sleep(0.05)
        else:
            raise TimeoutError("Chrome startup timed out")

        pages = get_json(f"http://127.0.0.1:{port}/json/list")
        page = next(p for p in pages if p.get("type") == "page")

        ws = websocket.create_connection(
            page["webSocketDebuggerUrl"],
            timeout=3,
            origin=f"http://127.0.0.1:{port}"
        )

        command_id = 0
        captured = []

        def process_event(message):
            if message.get("method") != "Runtime.consoleAPICalled":
                return

            for arg in message.get("params", {}).get("args", []):
                text = arg.get("value", "")
                if isinstance(text, str) and text.startswith("__O_CAPTURE__"):
                    try:
                        captured.append(json.loads(
                            text[len("__O_CAPTURE__"):]
                        ))
                    except ValueError:
                        pass

        def cdp(method, params=None):
            nonlocal command_id
            command_id += 1
            wanted = command_id

            ws.send(json.dumps({
                "id": wanted,
                "method": method,
                "params": params or {}
            }))

            while True:
                message = json.loads(ws.recv())
                process_event(message)

                if message.get("id") != wanted:
                    continue

                if "error" in message:
                    raise RuntimeError(message["error"])

                return message.get("result", {})

        cdp("Page.enable")
        cdp("Runtime.enable")

        # Do NOT call Storage.enable; it is not a valid CDP command.
        cdp("Page.addScriptToEvaluateOnNewDocument", {
            "source": PRELOAD
        })

        seen_origins = set()

        for url in urls:
            initial_origin = (
                f"{urlsplit(url).scheme}://{urlsplit(url).netloc}"
            )

            # Clear stale localStorage from previous links.
            for origin in seen_origins | {initial_origin}:
                try:
                    cdp("Storage.clearDataForOrigin", {
                        "origin": origin,
                        "storageTypes": "local_storage"
                    })
                except Exception:
                    pass

            captured.clear()
            cdp("Page.navigate", {"url": url})

            final_value = None
            deadline = time.monotonic() + 10

            while time.monotonic() < deadline:
                try:
                    response = cdp("Runtime.evaluate", {
                        "expression": READ_STORAGE,
                        "returnByValue": True
                    })

                    result = response.get("result", {}).get("value")

                    if isinstance(result, dict) and result.get("found"):
                        final_value = result.get("value")
                        break

                    if isinstance(result, dict) and result.get("url"):
                        p = urlsplit(result["url"])
                        seen_origins.add(f"{p.scheme}://{p.netloc}")

                except Exception:
                    pass

                if captured:
                    final_value = unwrap_captured(captured[-1]["raw"])
                    p = urlsplit(captured[-1].get("url", url))
                    if p.scheme and p.netloc:
                        seen_origins.add(f"{p.scheme}://{p.netloc}")
                    break

                time.sleep(0.05)

            if final_value is not None:
                try:
                    output = decode_o(final_value)
                    print(output, flush=True)
                except Exception:
                    # If the value is already the final URL, preserve it.
                    value = str(final_value).strip()
                    if value.startswith(("https://", "http://")):
                        print(value, flush=True)

    finally:
        if ws:
            try:
                ws.close()
            except Exception:
                pass

        if proc:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

        profile.cleanup()


raw = input("Paste URL(s), separated by commas: ").strip()

urls = [
    normalize_url(part)
    for part in raw.split(",")
    if part.strip()
]

if urls:
    run_decoder(urls)