import re
import unicodedata
from collections.abc import Callable
from typing import Any
from urllib.parse import ParseResult, urlparse

from aiohttp import ClientError, ClientSession
from bs4 import BeautifulSoup
from tiktoken import get_encoding


class PageCleaner:
    def __init__(self, remove_links: bool = True, token_limit: int = 1000):
        self.remove_links = remove_links
        self.token_limit = token_limit
        self.tokenizer = get_encoding("cl100k_base")
        self.invisible_chars = ["\ufeff", "\u200b", "\u2028", "\u2060"]

    def extract_title(self, soup: BeautifulSoup) -> str:
        title = (
            soup.title.string if soup.title and soup.title.string else "No title found"
        )
        return self._normalize_text(title)

    def extract_text(self, soup: BeautifulSoup) -> str:
        return soup.get_text(separator="\n", strip=True)

    def clean_text(self, text: str) -> str:
        text = self._normalize_text(text)
        text = re.sub(r"[ \t]+", " ", text)
        if self.remove_links:
            text = re.sub(r"\(https?://[^\s]+\)", "(links)", text)
        text = self._remove_emojis(text)
        text = self._remove_invisible_chars(text)
        return text.strip()

    def truncate_tokens(self, text: str) -> str:
        tokens = self.tokenizer.encode(text)
        truncated = self.tokenizer.decode(tokens[: self.token_limit])
        return self._remove_invisible_chars(truncated).strip()

    def _normalize_text(self, text: str) -> str:
        return unicodedata.normalize("NFKC", text).strip()

    def _remove_emojis(self, text: str) -> str:
        return "".join(c for c in text if not unicodedata.category(c).startswith("So"))

    def _remove_invisible_chars(self, text: str) -> str:
        for ch in self.invisible_chars:
            text = text.replace(ch, "")
        return text


class WebLoader:
    def __init__(self, valves, headers: dict, token_limit: int) -> None:
        self.valves = valves
        self.headers = headers
        self.cleaner = PageCleaner(
            remove_links=valves.REMOVE_LINKS,
            token_limit=token_limit,
        )

    def get_base_url(self, url: str) -> str:
        parsed_url: ParseResult = urlparse(url)
        return f"{parsed_url.scheme}://{parsed_url.netloc}"

    async def fetch_and_process_page(
        self, url: str, session: ClientSession
    ) -> dict[str, str]:
        try:
            async with session.get(url, headers=self.headers) as response:
                response.raise_for_status()
                html = await response.text()
        except ClientError as e:
            return {"url": url, "error": f"检索页面失败, 网络错误: {str(e)}"}
        except Exception as e:
            return {"url": url, "error": f"检索页面失败: {str(e)}"}

        soup = BeautifulSoup(html, "html.parser")
        title = self.cleaner.extract_title(soup)
        raw_text = self.cleaner.extract_text(soup)
        clean_text = self.cleaner.clean_text(raw_text)
        truncated = self.cleaner.truncate_tokens(clean_text)

        return {
            "title": title,
            "url": url,
            "content": truncated,
        }

    async def process_search_result(
        self, result: dict[str, str], session: ClientSession
    ) -> dict[str, str] | None:
        url = result["url"]
        snippet = result.get("content", "")

        if self.valves.IGNORED_WEBSITES:
            base_url = self.get_base_url(url)
            ignored_sites = [s.strip() for s in self.valves.IGNORED_WEBSITES.split(",")]
            if any(site in base_url for site in ignored_sites):
                return None

        result_data = await self.fetch_and_process_page(url, session)
        if "content" in result_data and "error" not in result_data:
            result_data["snippet"] = self.cleaner._remove_emojis(snippet)
            return result_data
        return None


class EventEmitter:
    def __init__(self, valves, event_emitter: Callable[[dict], Any] | None = None):
        self.valves = valves
        self.event_emitter = event_emitter

    async def _emit(self, type, data: dict[str, Any]) -> None:
        if not self.event_emitter:
            return

        await self.event_emitter({"type": type, "data": data})

    async def status(
        self,
        description: str = "未知状态",
        status: str = "in_progress",
        done: bool = False,
        action: str | None = "",
        urls: list[str] | None = None,
    ) -> None:
        if not self.valves.STATUS:
            return
        await self._emit(
            type="status",
            data={
                "description": description,
                "status": status,
                "done": done,
                "action": action,
                "urls": urls,
            },
        )

    async def citation(
        self,
        document: list[str],
        metadata: list[dict[str, str]],
        source: dict[str, str],
    ) -> None:
        if not self.valves.CITATION_LINKS:
            return
        await self._emit(
            type="citation",
            data={"document": document, "metadata": metadata, "source": source},
        )
