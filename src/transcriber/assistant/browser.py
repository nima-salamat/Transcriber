"""Controlled Chrome/Edge automation through a separate persistent browser profile.

The default Chrome profile is never attached to. The browser runs in its own
profile and exposes a loopback-only Chrome DevTools endpoint to Playwright.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from urllib.parse import quote, urlparse


class BrowserAutomationError(RuntimeError):
    """A browser could not be started or an interaction failed."""


class WindowsBrowserController:
    def __init__(self, profile_directory: str | Path):
        self.profile_directory = Path(profile_directory).expanduser()
        self._port: int | None = None
        self._process: subprocess.Popen | None = None

    @staticmethod
    def _find_browser() -> str | None:
        candidates = ["chrome.exe", "msedge.exe", "chrome", "microsoft-edge"]
        for command in candidates:
            resolved = shutil.which(command)
            if resolved:
                return resolved
        if sys.platform == "win32":
            roots = [
                Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")),
                Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")),
                Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")),
            ]
            relative = [
                Path("Google/Chrome/Application/chrome.exe"),
                Path("Microsoft/Edge/Application/msedge.exe"),
            ]
            for root in roots:
                for suffix in relative:
                    candidate = root / suffix
                    if candidate.is_file():
                        return str(candidate)
        return None

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def _debug_endpoint_ready(self, port: int) -> bool:
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.5) as response:
                return response.status == 200
        except (URLError, TimeoutError, OSError):
            return False

    def _ensure_browser(self) -> int:
        if self._port and self._debug_endpoint_ready(self._port):
            if self._process is None or self._process.poll() is None:
                return self._port
        executable = self._find_browser()
        if not executable:
            raise BrowserAutomationError(
                "Chrome or Microsoft Edge was not found. Install Chrome/Edge, or install "
                "the Playwright Chromium runtime with python -m playwright install chromium."
            )
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError as exc:
            raise BrowserAutomationError(
                "Browser automation needs Playwright. Install Transcriber's agent extras "
                'with pip install -e ".[agent]".'
            ) from exc

        self.profile_directory.mkdir(parents=True, exist_ok=True)
        port = self._free_port()
        flags = [
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={self.profile_directory}",
            "--no-first-run",
            "--no-default-browser-check",
            "--new-window",
        ]
        creationflags = 0
        if sys.platform == "win32":
            creationflags = (
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        try:
            self._process = subprocess.Popen(
                [executable, *flags],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creationflags,
            )
        except OSError as exc:
            raise BrowserAutomationError(f"Could not start the browser: {exc}") from exc
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise BrowserAutomationError("The browser exited before its automation endpoint became ready.")
            if self._debug_endpoint_ready(port):
                self._port = port
                return port
            time.sleep(0.2)
        self._process.terminate()
        raise BrowserAutomationError("The browser did not start its local automation endpoint in time.")

    def _with_page(self, callback):
        port = self._ensure_browser()
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise BrowserAutomationError("Playwright is not installed.") from exc
        playwright = sync_playwright().start()
        try:
            browser = playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{port}", timeout=12_000
            )
            contexts = browser.contexts
            if not contexts:
                raise BrowserAutomationError("The controlled browser has no active context.")
            context = contexts[0]
            pages = context.pages
            page = pages[-1] if pages else context.new_page()
            return callback(page)
        except BrowserAutomationError:
            raise
        except Exception as exc:
            raise BrowserAutomationError(f"Browser interaction failed: {exc}") from exc
        finally:
            # Stop only the Playwright client; the user-visible Chrome process and
            # its dedicated profile remain open for the next Agent browser action.
            playwright.stop()

    @staticmethod
    def _validate_url(value: str) -> str:
        url = str(value or "").strip()
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Only absolute HTTP and HTTPS URLs can be opened.")
        return url

    @staticmethod
    def _page_summary(page, *, include_elements: bool = True) -> dict:
        title = page.title()
        body = page.locator("body")
        text = body.inner_text(timeout=6_000) if body.count() else ""
        result = {
            "url": page.url,
            "title": title[:300],
            "text": text[:12_000],
            "truncated": len(text) > 12_000,
        }
        if include_elements:
            result["interactive_elements"] = page.locator(
                "a,button,input,textarea,select,[role='button'],[role='link']"
            ).evaluate_all(
                """items => items.filter(el => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    return rect.width > 0 && rect.height > 0 &&
                           style.visibility !== 'hidden' && style.display !== 'none';
                }).slice(0, 60).map((el, index) => ({
                    index,
                    tag: el.tagName.toLowerCase(),
                    role: el.getAttribute('role') || '',
                    label: (el.getAttribute('aria-label') || el.innerText ||
                            el.getAttribute('placeholder') || el.getAttribute('name') || '').trim().slice(0, 180),
                    type: el.getAttribute('type') || '',
                    href: el.getAttribute('href') || ''
                }))"""
            )
        return result

    def open(self, url: str) -> dict:
        target = self._validate_url(url)

        def navigate(page):
            page.goto(target, wait_until="domcontentloaded", timeout=35_000)
            return self._page_summary(page)

        return self._with_page(navigate)

    def search(self, query: str, *, engine: str = "google") -> dict:
        term = str(query or "").strip()
        if not term or len(term) > 500:
            raise ValueError("Enter a search query (maximum 500 characters).")
        base = "https://www.google.com/search?q=" if engine == "google" else "https://www.bing.com/search?q="
        return self.open(base + quote(term, safe=""))

    def snapshot(self) -> dict:
        return self._with_page(lambda page: self._page_summary(page))

    def click(self, *, text: str = "", selector: str = "", role: str = "") -> dict:
        if not any((str(text).strip(), str(selector).strip(), str(role).strip())):
            raise ValueError("Specify text, a CSS selector or an ARIA role.")
        def interact(page):
            if selector:
                locator = page.locator(selector).first
            elif role:
                locator = page.get_by_role(role, name=text or None).first
            else:
                locator = page.get_by_text(text, exact=False).first
            locator.click(timeout=12_000)
            try:
                page.wait_for_load_state("domcontentloaded", timeout=5_000)
            except Exception:
                pass
            return self._page_summary(page)
        return self._with_page(interact)

    def fill(
        self,
        value: str,
        *,
        selector: str = "",
        label: str = "",
        placeholder: str = "",
    ) -> dict:
        if sum(bool(item.strip()) for item in (selector, label, placeholder)) != 1:
            raise ValueError("Provide exactly one of selector, label or placeholder.")
        if len(str(value)) > 8_000:
            raise ValueError("Form values are limited to 8,000 characters.")
        def interact(page):
            if selector:
                locator = page.locator(selector).first
            elif label:
                locator = page.get_by_label(label, exact=False).first
            else:
                locator = page.get_by_placeholder(placeholder, exact=False).first
            locator.fill(str(value), timeout=12_000)
            return self._page_summary(page, include_elements=False)
        return self._with_page(interact)

    def press(self, key: str, *, selector: str = "") -> dict:
        value = str(key or "").strip()
        if value.casefold() not in {
            "enter", "tab", "escape", "esc", "arrowdown", "arrowup", "home", "end",
            "ctrl+a", "ctrl+l", "ctrl+f", "ctrl+enter", "shift+tab",
        }:
            raise ValueError("This key is not in the browser-agent keyboard allowlist.")
        def interact(page):
            if selector:
                page.locator(selector).first.press(value, timeout=8_000)
            else:
                page.keyboard.press(value)
            return self._page_summary(page)
        return self._with_page(interact)

    def back(self) -> dict:
        def navigate(page):
            page.go_back(wait_until="domcontentloaded", timeout=15_000)
            return self._page_summary(page)
        return self._with_page(navigate)

    def screenshot(self, output_directory: str | Path) -> dict:
        directory = Path(output_directory)
        directory.mkdir(parents=True, exist_ok=True)
        def capture(page):
            target = directory / f"browser-{int(time.time() * 1000)}.png"
            page.screenshot(path=str(target), full_page=False)
            return {"path": str(target), "url": page.url, "title": page.title()}
        return self._with_page(capture)

    def close(self) -> dict:
        process = self._process
        self._process = None
        self._port = None
        if process is None or process.poll() is not None:
            return {"closed": True, "already_closed": True}
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        return {"closed": True}
