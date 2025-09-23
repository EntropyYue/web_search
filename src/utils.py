import ipaddress
import re
import unicodedata
from collections.abc import Callable
from typing import Any
from urllib.parse import ParseResult, urlparse

from aiohttp import ClientError, ClientSession
from bs4 import BeautifulSoup
from langchain_community.retrievers import BM25Retriever as LCBM25Retriever
from pydantic import BaseModel
from tiktoken import get_encoding


class LoadResult(BaseModel):
    text: str | None = None
    metadata: dict[str, str] | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.error:
            return {"error": self.error}
        return {"text": self.text, "metadata": self.metadata}


class PageCleaner:
    def __init__(self, token_limit: int = 1000):
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
        self.cleaner = PageCleaner(token_limit=token_limit)

    def get_base_url(self, url: str) -> str:
        parsed_url: ParseResult = urlparse(url)
        return f"{parsed_url.scheme}://{parsed_url.netloc}"

    def _is_safe_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            if parsed.scheme != "https":
                return False
            hostname = parsed.hostname or ""
            try:
                ip = ipaddress.ip_address(hostname)
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_reserved
                    or ip.is_link_local
                ):
                    return False
            except ValueError:
                pass
            return not (
                hostname in ("localhost",)
                or hostname.endswith(".local")
                or hostname.endswith(".localdomain")
            )
        except Exception:
            return False

    async def fetch_and_process_page(
        self, url: str, session: ClientSession
    ) -> LoadResult:
        if not self._is_safe_url(url):
            return LoadResult(error="不安全的URL, 仅支持HTTPS和公共网络")
        try:
            async with session.get(url, headers=self.headers) as response:
                response.raise_for_status()
                html = await response.text()
        except ClientError as e:
            return LoadResult(error=f"检索页面失败, 网络错误: {str(e)}")
        except Exception as e:
            return LoadResult(error=f"检索页面失败: {str(e)}")

        soup = BeautifulSoup(html, "html.parser")
        title = self.cleaner.extract_title(soup)
        raw_text = self.cleaner.extract_text(soup)
        clean_text = self.cleaner.clean_text(raw_text)
        truncated = self.cleaner.truncate_tokens(clean_text)

        return LoadResult(
            text=truncated,
            metadata={
                "title": title,
                "url": url,
            },
        )

    async def process_search_result(
        self, result: dict[str, str], session: ClientSession
    ) -> LoadResult | None:
        url = result["url"]
        snippet = result.get("content", "")

        if self.valves.IGNORED_WEBSITES:
            base_url = self.get_base_url(url)
            ignored_sites = [s.strip() for s in self.valves.IGNORED_WEBSITES.split(",")]
            if any(site in base_url for site in ignored_sites):
                return None

        result_data = await self.fetch_and_process_page(url, session)
        if result_data.text and result_data.metadata:
            result_data.metadata["snippet"] = self.cleaner._remove_emojis(snippet)
            return result_data
        return None


class SearchEngine:
    def __init__(self, url: str, max_result: int, headers: dict) -> None:
        self.url = url
        self.max_result = max_result
        self.headers = headers

    async def search(self, query: str, session: ClientSession) -> dict[str, Any]:
        params = {"q": query, "format": "json"}
        try:
            async with session.get(
                self.url, params=params, headers=self.headers
            ) as resp:
                resp.raise_for_status()
                result = await resp.json()
            if "results" in result:
                result["results"] = result["results"][: self.max_result]
            return result
        except ClientError as e:
            raise RuntimeError(f"搜索时出错: {str(e)}") from e


class BM25Retriever:
    def __init__(self, documents: list[LoadResult], k=5) -> None:
        texts = [doc.text or "" for doc in documents if doc.text]
        metadatas = [doc.metadata or {} for doc in documents if doc.metadata]
        self.retriever = LCBM25Retriever.from_texts(texts=texts, metadatas=metadatas)
        self.retriever.k = k

    async def ainvoke(self, query: str) -> list[LoadResult]:
        results = await self.retriever.ainvoke(query)
        return [
            LoadResult(text=doc.page_content, metadata=doc.metadata) for doc in results
        ]


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
        description: str | None = None,
        status: str = "in_progress",
        done: bool = False,
        action: str | None = "web_search",
        queries: list[str] | None = None,
        count: int | None = None,
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
                "queries": queries,
                "count": count,
                "urls": urls,
            },
        )

    async def queries(self, queries: list[str]) -> None:
        await self.status(
            action="web_search_queries_generated",
            queries=queries,
        )

    async def urls(self, urls: list[str]) -> None:
        await self.status(
            action="web_search",
            description="Searched {{count}} sites",
            urls=urls,
        )

    async def retrieval(self, queries: list[str]) -> None:
        await self.status(
            action="queries_generated",
            queries=queries,
        )

    async def fetched(self, count: int) -> None:
        await self.status(
            action="sources_retrieved",
            count=count,
            done=True,
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
