from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from utils import ROOT_DIR


BROWSER_PROFILES_DIR = ROOT_DIR / "browser_profiles"


class WebAIClientError(RuntimeError):
    pass


class WebAINeedsUserAction(WebAIClientError):
    pass


@dataclass
class WebAIResponse:
    text: str


class BaseWebAIClient:
    provider = "web"
    start_url = ""
    input_selectors: tuple[str, ...] = ()
    send_selectors: tuple[str, ...] = ()
    response_selectors: tuple[str, ...] = ()
    busy_selectors: tuple[str, ...] = ()

    def __init__(self, profile_dir: Path | None = None, headless: bool = False, timeout_ms: int = 180_000) -> None:
        self.profile_dir = profile_dir or (BROWSER_PROFILES_DIR / self.provider)
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.playwright = None
        self.context = None
        self.page = None

    def open(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise WebAIClientError("尚未安裝 Playwright。請執行 pip install -r requirements.txt 後再跑 playwright install chromium。") from exc
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.playwright = sync_playwright().start()
        try:
            self.context = self.playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=self.headless,
                viewport={"width": 1400, "height": 950},
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as exc:
            self.playwright.stop()
            raise WebAIClientError(
                f"無法啟動瀏覽器 profile：{self.profile_dir}。"
                "請先關閉所有由本工具開啟的 ChatGPT/Gemini 瀏覽器視窗後重試；"
                "若仍失敗，可暫時重新命名 browser_profiles 對應資料夾讓系統建立新 profile。"
            ) from exc
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.goto(self.start_url, wait_until="domcontentloaded", timeout=60_000)
        try:
            self.page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            pass
        self.dismiss_common_popups()

    def close(self) -> None:
        if self.context:
            self.context.close()
        if self.playwright:
            self.playwright.stop()

    def pause_for_user(self, message: str) -> None:
        print(message)
        if sys.stdin and sys.stdin.isatty():
            input("完成人工處理後按 Enter 繼續...")

    def _require_page(self):
        if self.page is None:
            raise WebAIClientError("瀏覽器尚未開啟")
        return self.page

    def page_diagnostic(self) -> str:
        page = self._require_page()
        try:
            title = page.title()
        except Exception:
            title = ""
        try:
            body = page.locator("body").inner_text(timeout=5_000)
        except Exception:
            body = ""
        compact_body = " ".join(body.split())[:500]
        return f"url={page.url}; title={title}; body={compact_body}"

    def dismiss_common_popups(self) -> None:
        page = self._require_page()
        labels = [
            "Continue",
            "Got it",
            "Not now",
            "Accept",
            "I agree",
            "稍後",
            "知道了",
            "繼續",
            "接受",
            "同意",
        ]
        for label in labels:
            for selector in (f"button:has-text('{label}')", f"[role='button']:has-text('{label}')"):
                try:
                    button = page.locator(selector).first
                    if button.is_visible(timeout=500):
                        button.click(timeout=1_000)
                        page.wait_for_timeout(500)
                        break
                except Exception:
                    continue

    def ensure_ready(self) -> None:
        page = self._require_page()
        body = page.locator("body").inner_text(timeout=30_000).lower()
        url = page.url.lower()
        blocked_terms = ["captcha", "verify you are human", "unusual activity", "rate limit", "too many requests"]
        login_terms = ["log in", "sign in", "登入", "login"]
        if any(term in body or term in url for term in blocked_terms):
            raise WebAINeedsUserAction("偵測到驗證、流量限制或需要人工處理的畫面。")
        if any(term in body for term in login_terms) and not self._has_visible_input():
            raise WebAINeedsUserAction("偵測到可能尚未登入，請在開啟的瀏覽器中登入。")
        if not self._has_visible_input():
            raise WebAINeedsUserAction(f"找不到可輸入訊息的欄位，可能需要人工關閉彈窗或重新登入。診斷：{self.page_diagnostic()}")

    def _first_visible(self, selectors: tuple[str, ...], timeout_ms: int = 2_000):
        page = self._require_page()
        for selector in selectors:
            try:
                locator = page.locator(selector).last
                locator.wait_for(state="visible", timeout=timeout_ms)
                return locator
            except Exception:
                continue
        return None

    def _has_visible_input(self) -> bool:
        if self._first_visible(self.input_selectors, timeout_ms=1_000) is not None:
            return True
        if self._generic_editable(timeout_ms=1_000) is not None:
            return True
        if self._role_textbox(timeout_ms=1_000) is not None:
            return True
        return False

    def _generic_editable(self, timeout_ms: int = 2_000):
        page = self._require_page()
        try:
            editable = page.locator("[contenteditable='true']").last
            editable.wait_for(state="visible", timeout=timeout_ms)
            return editable
        except Exception:
            return None

    def _role_textbox(self, timeout_ms: int = 2_000):
        page = self._require_page()
        try:
            textbox = page.get_by_role("textbox").last
            textbox.wait_for(state="visible", timeout=timeout_ms)
            return textbox
        except Exception:
            return None

    def _input_box(self, timeout_ms: int = 10_000):
        return self._first_visible(self.input_selectors, timeout_ms=timeout_ms) or self._generic_editable(timeout_ms=2_000) or self._role_textbox(timeout_ms=2_000)

    def submit(self, text: str) -> None:
        self.ensure_ready()
        input_box = self._input_box(timeout_ms=10_000)
        if input_box is None:
            raise WebAINeedsUserAction(f"找不到輸入欄位。診斷：{self.page_diagnostic()}")
        input_box.click()
        try:
            input_box.fill(text)
        except Exception:
            page = self._require_page()
            page.keyboard.press("Control+A")
            page.keyboard.insert_text(text)
        send_button = self._first_visible(self.send_selectors, timeout_ms=3_000)
        if send_button:
            send_button.click()
        else:
            self._require_page().keyboard.press("Enter")

    def wait_for_response(self) -> None:
        page = self._require_page()
        page.wait_for_timeout(3_000)
        deadline_ms = self.timeout_ms
        elapsed = 0
        while elapsed < deadline_ms:
            busy = False
            for selector in self.busy_selectors:
                try:
                    if page.locator(selector).count() > 0 and page.locator(selector).last.is_visible(timeout=500):
                        busy = True
                        break
                except Exception:
                    continue
            if not busy and self.get_response_text().strip():
                return
            page.wait_for_timeout(2_000)
            elapsed += 2_000
        raise WebAINeedsUserAction("等待 AI 回覆逾時或無法判斷是否完成。")

    def get_response_text(self) -> str:
        page = self._require_page()
        for selector in self.response_selectors:
            try:
                loc = page.locator(selector)
                count = loc.count()
                if count:
                    text = loc.nth(count - 1).inner_text(timeout=5_000).strip()
                    if text:
                        return text
            except Exception:
                continue
        raise WebAINeedsUserAction("找不到 AI 回覆文字，可能是網頁 UI 已改版。")


class ChatGPTWebClient(BaseWebAIClient):
    provider = "chatgpt"
    start_url = "https://chatgpt.com/"
    input_selectors = (
        "textarea#prompt-textarea",
        "textarea[data-testid='prompt-textarea']",
        "textarea[placeholder*='Message']",
        "textarea[placeholder*='Ask']",
        "textarea[aria-label*='Message']",
        "div#prompt-textarea[contenteditable='true']",
        "div[contenteditable='true'][role='textbox']",
        "[contenteditable='true'][data-placeholder*='Message']",
        "[contenteditable='true'][data-placeholder*='Ask']",
        "[contenteditable='true'][aria-label*='Message']",
        "div.ProseMirror[contenteditable='true']",
        "[contenteditable='true']",
    )
    send_selectors = (
        "button[data-testid='send-button']",
        "button[data-testid='composer-send-button']",
        "button[aria-label*='Send']",
        "button[aria-label*='Submit']",
        "button[aria-label*='送出']",
    )
    response_selectors = (
        "[data-message-author-role='assistant']",
        "article:has-text('')",
        ".markdown",
    )
    busy_selectors = (
        "button[data-testid='stop-button']",
        "button[aria-label*='Stop']",
        "button[aria-label*='停止']",
    )


class GeminiWebClient(BaseWebAIClient):
    provider = "gemini"
    start_url = "https://gemini.google.com/"
    input_selectors = (
        "rich-textarea div[contenteditable='true']",
        "div[contenteditable='true'][role='textbox']",
        "div[contenteditable='true'][aria-label*='Enter']",
        "div[contenteditable='true'][aria-label*='輸入']",
        "div[contenteditable='true'][data-placeholder*='Enter']",
        "div[contenteditable='true'][data-placeholder*='Ask']",
        "textarea",
        "[contenteditable='true']",
    )
    send_selectors = (
        "button[aria-label*='Send']",
        "button[aria-label*='送出']",
        "button.send-button",
    )
    response_selectors = (
        "message-content",
        ".model-response-text",
        "div[class*='response']",
    )
    busy_selectors = (
        "button[aria-label*='Stop']",
        "button[aria-label*='停止']",
        "mat-progress-spinner",
    )


def make_web_ai_client(provider: str, profile_dir: Path | None = None, headless: bool = False, timeout_ms: int = 180_000) -> BaseWebAIClient:
    provider = provider.strip().lower()
    if provider == "chatgpt":
        return ChatGPTWebClient(profile_dir=profile_dir, headless=headless, timeout_ms=timeout_ms)
    if provider == "gemini":
        return GeminiWebClient(profile_dir=profile_dir, headless=headless, timeout_ms=timeout_ms)
    raise ValueError("provider 必須是 chatgpt 或 gemini")
