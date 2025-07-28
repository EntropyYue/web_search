import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, ParseResult
import re
import unicodedata
from typing import Callable, Any


class HelpFunctions:
    def __init__(self, value) -> None:
        self.valves = value

    def get_base_url(self, url: str) -> str:
        parsed_url: ParseResult = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        return base_url

    def generate_excerpt(self, content: str, max_length=200) -> str:
        return content[:max_length] + "..." if len(content) > max_length else content

    def format_text(self, original_text: str) -> str:
        soup = BeautifulSoup(original_text, "html.parser")
        formatted_text = soup.get_text(separator=" ", strip=True)
        formatted_text = unicodedata.normalize("NFKC", formatted_text)
        formatted_text = re.sub(r"\s+", " ", formatted_text)
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

    def fetch_and_process_page(self, url: str) -> dict[str, str]:
        try:
            response_site = requests.get(
                self.valves.JINA_READER_BASE_URL + url, timeout=20
            )
            response_site.encoding = response_site.apparent_encoding
            response_site.raise_for_status()
            html_content = response_site.text
            soup = BeautifulSoup(html_content, "html.parser")
            page_title = (
                soup.title.string
                if soup.title and soup.title.string
                else "No title found"
            )
            page_title = unicodedata.normalize("NFKC", page_title.strip())
            page_title = self.remove_emojis(page_title)

            content_site = self.format_text(soup.get_text(separator=" ", strip=True))
            truncated_content = self.truncate_to_n_words(
                content_site, self.valves.PAGE_CONTENT_WORDS_LIMIT
            )
            return {
                "title": page_title,
                "url": url,
                "content": truncated_content,
            }
        except requests.exceptions.RequestException as e:
            return {
                "url": url,
                "content": f"检索页面失败,错误: {str(e)}",
            }

    def process_search_result(self, result: dict[str, str]) -> dict[str, str] | None:
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

        result_data = self.fetch_and_process_page(url_site)
        if "content" in result_data and "检索页面失败" not in result_data["content"]:
            result_data["snippet"] = self.remove_emojis(snippet)
            return result_data
        return None

    def truncate_to_n_words(self, text: str, token_limit: int) -> str:
        tokens = text.split()
        truncated_tokens = tokens[:token_limit]
        return " ".join(truncated_tokens)


class EventEmitter:
    def __init__(self, event_emitter: Callable[[dict], Any] | None = None):
        self.event_emitter = event_emitter

    async def emit(
        self,
        description="未知状态",
        status="in_progress",
        done=False,
        action="",
        urls=[],
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
