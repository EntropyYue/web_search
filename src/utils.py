import re
import unicodedata
from collections.abc import Callable
from typing import Any
from urllib.parse import ParseResult, urlparse

from aiohttp import ClientSession
from bs4 import BeautifulSoup
from tiktoken import get_encoding

class HelpFunctions:
    def __init__(self, value) -> None:
        self.valves = value
        self.tokenizer = get_encoding("cl100k_base") 

    def get_base_url(self, url: str) -> str:
        parsed_url: ParseResult = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        return base_url

    def generate_excerpt(self, content: str, max_length=200) -> str:
        return content[:max_length] + "..." if len(content) > max_length else content

    def format_text(self, original_text: str) -> str:
        soup = BeautifulSoup(original_text, "html.parser")
        formatted_text = soup.get_text(separator="\n", strip=True)
        formatted_text = unicodedata.normalize("NFKC", formatted_text)
        formatted_text = re.sub(r"[ \t]+", " ", formatted_text)
        formatted_text = formatted_text.strip()
        formatted_text = self.remove_emojis(formatted_text)
        if self.valves.REMOVE_LINKS:
            formatted_text = self.replace_urls_with_text(formatted_text)
        return formatted_text

    def remove_emojis(self, text: str) -> str:
        return "".join(c for c in text if not unicodedata.category(c).startswith("So"))

    def replace_urls_with_text(self, text: str, replacement="(links)") -> str:
        pattern = r"\(https?://[^\s]+\)"
        return re.sub(pattern, replacement, text)

    async def fetch_and_process_page(
        self, url: str, session: ClientSession
    ) -> dict[str, str]:
        try:
            response_site = await session.get(self.valves.JINA_READER_BASE_URL + url)
            response_site.raise_for_status()
            html_content = await response_site.text()
            soup = BeautifulSoup(html_content, "html.parser")
            page_title = (
                soup.title.string
                if soup.title and soup.title.string
                else "No title found"
            )
            page_title = unicodedata.normalize("NFKC", page_title.strip())
            page_title = self.remove_emojis(page_title)

            content_site = self.format_text(soup.get_text(separator="\n", strip=True))
            truncated_content = self.truncate_to_n_words(
                content_site, self.valves.PAGE_CONTENT_WORDS_LIMIT
            )
            return {
                "title": page_title,
                "url": url,
                "content": truncated_content,
            }
        except BaseException as e:
            return {
                "url": url,
                "content": f"检索页面失败, 错误: {str(e)}",
            }

    async def process_search_result(
        self, result: dict[str, str], session: ClientSession
    ) -> dict[str, str] | None:
        self.remove_emojis(result["title"])
        url_site = result["url"]
        snippet = result.get("content", "")
        if self.valves.IGNORED_WEBSITES:
            base_url = self.get_base_url(url_site)
            if any(
                ignored_site.strip() in base_url
                for ignored_site in self.valves.IGNORED_WEBSITES.split(",")
            ):
                return None

        result_data = await self.fetch_and_process_page(url_site, session)
        if "content" in result_data and "检索页面失败" not in result_data["content"]:
            result_data["snippet"] = self.remove_emojis(snippet)
            return result_data
        return None

    def truncate_to_n_words(self, text: str, token_limit: int) -> str:
        tokens = self.tokenizer.encode(text)
        truncated_tokens = tokens[:token_limit]
        deocoded_tokens = self.tokenizer.decode(truncated_tokens)
        return deocoded_tokens


class EventEmitter:
    def __init__(self, event_emitter: Callable[[dict], Any] | None = None):
        self.event_emitter = event_emitter

    async def emit(
        self,
        description="未知状态",
        status="in_progress",
        done=False,
        action="",
        urls=None,
    ):
        if self.event_emitter:
            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "status": status,
                        "description": description,
                        "done": done,
                        "action": action,
                        "urls": urls,
                    },
                }
            )
