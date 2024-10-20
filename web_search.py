"""
title: Web Search using SearXNG and Scrape first N Pages
author: constLiakos with enhancements by justinh-rahb and ther3zz
funding_url: https://github.com/EntropyYue/web_search
version: 0.3.0
license: MIT
"""

import os
import requests
from datetime import datetime
import json
from requests import get
from bs4 import BeautifulSoup
import concurrent.futures
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin
import re
import unicodedata
from pydantic import BaseModel, Field
import asyncio
from typing import Callable, Any


class HelpFunctions:
    def __init__(self):
        pass

    def get_base_url(self, url):
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"
        return base_url

    def generate_excerpt(self, content, max_length=200):
        return content[:max_length] + "..." if len(content) > max_length else content

    def format_text(self, original_text, valves):
        soup = BeautifulSoup(original_text, "html.parser")
        formatted_text = soup.get_text(separator=" ", strip=True)
        formatted_text = unicodedata.normalize("NFKC", formatted_text)
        formatted_text = re.sub(r"\s+", " ", formatted_text)
        formatted_text = formatted_text.strip()
        formatted_text = self.remove_emojis(formatted_text)
        if valves.REMOVE_LINKS:
            formatted_text = self.replace_urls_with_text(formatted_text)
        return formatted_text

    def remove_emojis(self, text):
        return "".join(c for c in text if not unicodedata.category(c).startswith("So"))

    def replace_urls_with_text(self, text, replacement="(links)"):
        pattern = r'\(https?://[^\s]+\)'
        return re.sub(pattern, replacement, text)

    def process_search_result(self, result, valves):
        title_site = self.remove_emojis(result["title"])
        url_site = result["url"]
        snippet = result.get("content", "")

        # Check if the website is in the ignored list, but only if IGNORED_WEBSITES is not empty
        if valves.IGNORED_WEBSITES:
            base_url = self.get_base_url(url_site)
            if any(
                ignored_site.strip() in base_url
                for ignored_site in valves.IGNORED_WEBSITES.split(",")
            ):
                return None

        try:
            response_site = requests.get(
                valves.JINA_READER_BASE_URL + url_site, timeout=20
            )
            response_site.raise_for_status()
            html_content = response_site.text

            soup = BeautifulSoup(html_content, "html.parser")
            content_site = self.format_text(soup.get_text(separator=" ", strip=True), valves)

            truncated_content = self.truncate_to_n_words(
                content_site, valves.PAGE_CONTENT_WORDS_LIMIT
            )

            return {
                "title": title_site,
                "url": url_site,
                "content": truncated_content,
                "snippet": self.remove_emojis(snippet),
            }

        except requests.exceptions.RequestException as e:
            return None

    def truncate_to_n_words(self, text, token_limit):
        tokens = text.split()
        truncated_tokens = tokens[:token_limit]
        return " ".join(truncated_tokens)

    def rag_process(self, context: str, valves) -> str:
        url = "http://127.0.0.1:8080/retrieval/api/v1/process/text"
        self.headers = {
            "Authorization": f"Bearer {valves.OPEN_WEBUI_TOKEN}",
            "accept": "application/json",
            "Content-Type": "application/json",
        }
        collection = str(hash(context))
        data = {"name": "rag_search", "content": context, "collection_name": collection}
        response = requests.post(url, headers=self.headers, json=data)
        if response.status_code == 200:
            return collection
        else:
            raise Exception(f"Error processing text: {response.json()}")

    def rag_search(self, context: str, query: str, valves) -> dict:
        collection = self.rag_process(context, valves)
        url = "http://127.0.0.1:8080/retrieval/api/v1/query/collection"
        data = {
            "collection_names": [collection],
            "query": query,
            "k": 0,
            "r": 0,
            "hybrid": True,
        }
        response = requests.post(url, headers=self.headers, json=data)
        if response.status_code == 200:
            return response.json()["documents"][0]
        else:
            raise Exception(f"Error searching collection: {response.json()}")


class EventEmitter:
    def __init__(self, event_emitter: Callable[[dict], Any] = None):
        self.event_emitter = event_emitter

    async def emit(self, description="未知状态", status="in_progress", done=False):
        if self.event_emitter:
            await self.event_emitter(
                {
                    "type": "status",
                    "data": {
                        "status": status,
                        "description": description,
                        "done": done,
                    },
                }
            )

    async def message(self, content):
        if self.event_emitter:
            await self.event_emitter(
                {
                    "type": "message",
                    "data": {
                        "content": content,
                    },
                }
            )


class Tools:
    class Valves(BaseModel):
        SEARXNG_ENGINE_API_BASE_URL: str = Field(
            default="https://example.com/search",
            description="搜索引擎的基础URL",
        )
        IGNORED_WEBSITES: str = Field(
            default="",
            description="以逗号分隔的要忽略的网站列表",
        )
        RETURNED_SCRAPPED_PAGES_NO: int = Field(
            default=3,
            description="要分析的搜索引擎结果数",
        )
        SCRAPPED_PAGES_NO: int = Field(
            default=5,
            description="已分页的总页数。理想情况下，大于返回的页面之一",
        )
        PAGE_CONTENT_WORDS_LIMIT: int = Field(
            default=5000,
            description="限制每页的字数",
        )
        CITATION_LINKS: bool = Field(
            default=False,
            description="如果为True，则发送带有链接的自定义引用",
        )
        JINA_READER_BASE_URL: str = Field(
            default="https://r.jina.ai/",
            description="Jina Reader的基础URL",
        )
        RAG_ENABLE: bool = Field(
            default=False,
            description="是否启用RAG",
        )
        REMOVE_LINKS: bool = Field(
            default=True,
            description="检索中的返回是否移除链接",
        )
        OPEN_WEBUI_TOKEN: str = Field(
            default="",
            description="open-webui令牌",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
        }

    async def search_web(
        self,
        query: str,
        __event_emitter__: Callable[[dict], Any] = None,
    ) -> str:
        """
        搜索网络并获取相关页面的内容，搜索未知知识、新闻、信息、公共联系信息、天气等

        :params query: 搜索中使用的关键词

        :return: The content of the pages in json format.
        """
        functions = HelpFunctions()
        emitter = EventEmitter(__event_emitter__)

        await emitter.emit(f"正在搜索: {query}")

        search_engine_url = self.valves.SEARXNG_ENGINE_API_BASE_URL

        # Ensure RETURNED_SCRAPPED_PAGES_NO does not exceed SCRAPPED_PAGES_NO
        if self.valves.RETURNED_SCRAPPED_PAGES_NO > self.valves.SCRAPPED_PAGES_NO:
            self.valves.RETURNED_SCRAPPED_PAGES_NO = self.valves.SCRAPPED_PAGES_NO

        params = {
            "q": query,
            "format": "json",
            "number_of_results": self.valves.RETURNED_SCRAPPED_PAGES_NO,
        }

        try:
            await emitter.emit("正在向搜索引擎发送请求")
            resp = requests.get(
                search_engine_url, params=params, headers=self.headers, timeout=120
            )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            limited_results = results[: self.valves.SCRAPPED_PAGES_NO]
            await emitter.emit(f"返回了 {len(limited_results)} 个搜索结果")

        except requests.exceptions.RequestException as e:
            await emitter.emit(
                status="error",
                description=f"搜索时出错: {str(e)}",
                done=True,
            )
            return json.dumps({"error": str(e)})

        results_json = []
        if limited_results:
            await emitter.emit(f"正在处理搜索结果")

            try:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    futures = [
                        executor.submit(
                            functions.process_search_result, result, self.valves
                        )
                        for result in limited_results
                    ]
                    for future in concurrent.futures.as_completed(futures):
                        result_json = future.result()
                        if result_json:
                            try:
                                if self.valves.RAG_ENABLE:
                                    result_json["content"] = functions.rag_search(
                                        result_json["content"], query, self.valves
                                    )
                                json.dumps(result_json)
                                results_json.append(result_json)
                            except (TypeError, ValueError, Exception) as e:
                                print(f"处理时出错: {str(e)}")
                                continue
                        if len(results_json) >= self.valves.RETURNED_SCRAPPED_PAGES_NO:
                            break

            except BaseException as e:
                await emitter.emit(
                    status="error",
                    description=f"处理时出错: {str(e)}",
                    done=True,
                )

            results_json = results_json[: self.valves.RETURNED_SCRAPPED_PAGES_NO]

            if self.valves.CITATION_LINKS and __event_emitter__:
                if len(results_json):
                    for result in results_json:
                        await __event_emitter__(
                            {
                                "type": "citation",
                                "data": {
                                    "document": [result["content"]],
                                    "metadata": [{"source": result["url"]}],
                                    "source": {"name": result["title"]},
                                },
                            }
                        )
                if len(results_json):
                    await emitter.message(
                        "\n<details>\n<summary>检索到的网站标题</summary>\n"
                    )
                    for result in results_json:
                        await emitter.message("> " + result["title"] + "\n\n")
                    await emitter.message("\n</details>\n")

        await emitter.emit(
            status="complete",
            description=f"网络搜索已完成,将从 {len(results_json)} 个页面检索内容",
            done=True,
        )

        return json.dumps(results_json, indent=4, ensure_ascii=False)

    async def get_website(
        self, url: str, __event_emitter__: Callable[[dict], Any] = None
    ) -> str:
        """
        访问输入的网站并获取其内容

        :params url: The URL of the website.

        :return: The content of the website in json format.
        """
        functions = HelpFunctions()
        emitter = EventEmitter(__event_emitter__)

        await emitter.emit(f"正在从URL获取内容: {url}")

        results_json = []

        try:
            response_site = requests.get(
                self.valves.JINA_READER_BASE_URL + url,
                headers=self.headers,
                timeout=120,
            )
            response_site.raise_for_status()
            html_content = response_site.text

            await emitter.emit("解析网站内容")

            soup = BeautifulSoup(html_content, "html.parser")

            page_title = soup.title.string if soup.title else "No title found"
            page_title = unicodedata.normalize("NFKC", page_title.strip())
            page_title = functions.remove_emojis(page_title)
            title_site = page_title
            url_site = url
            content_site = functions.format_text(
                soup.get_text(separator=" ", strip=True)
            )

            truncated_content = functions.truncate_to_n_words(
                content_site, self.valves.PAGE_CONTENT_WORDS_LIMIT
            )

            result_site = {
                "title": title_site,
                "url": url_site,
                "content": truncated_content,
                "excerpt": functions.generate_excerpt(content_site),
            }

            results_json.append(result_site)

            if self.valves.CITATION_LINKS and __event_emitter__:
                await __event_emitter__(
                    {
                        "type": "citation",
                        "data": {
                            "document": [truncated_content],
                            "metadata": [{"source": url_site}],
                            "source": {"name": title_site},
                        },
                    }
                )

            await emitter.emit(
                status="complete",
                description="已成功检索和处理网站内容",
                done=True,
            )

        except requests.exceptions.RequestException as e:
            results_json.append(
                {
                    "url": url,
                    "content": f"检索页面失败,错误: {str(e)}",
                }
            )

            await emitter.emit(
                status="error",
                description=f"获取网站内容时出错: {str(e)}",
                done=True,
            )

        return json.dumps(results_json, indent=4, ensure_ascii=False)
