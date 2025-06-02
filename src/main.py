"""
title: Web Search
author: EntropyYue
funding_url: https://github.com/EntropyYue/web_search
version: 0.6.1
license: MIT
"""

import requests
import json
import concurrent.futures
from pydantic import BaseModel, Field
from typing import Callable, Any

from utils import HelpFunctions, EventEmitter


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
        PAGE_CONTENT_WORDS_LIMIT: int = Field(
            default=5000,
            description="限制每页的字数",
        )
        CITATION_LINKS: bool = Field(
            default=False,
            description="如果为True，则发送带有链接的自定义引用",
        )
        JINA_READER_BASE_URL: str = Field(
            default="",
            description="Jina Reader的基础URL，使用默认参数以关闭",
        )
        REMOVE_LINKS: bool = Field(
            default=True,
            description="检索中的返回是否移除链接",
        )
        STATUS: bool = Field(
            default=True,
            description="如果为True，则发送状态",
        )

    def __init__(self):
        self.valves = self.Valves()
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"
        }

    async def search_web(
        self,
        query: str,
        __event_emitter__: Callable[[dict], Any] | None = None,
    ) -> str:
        """
        搜索网络并获取相关页面的内容，搜索未知知识、新闻、信息、公共联系信息、天气等

        :params query: 搜索中使用的关键词

        :return: The content of the pages in json format.
        """
        functions = HelpFunctions()
        emitter = EventEmitter(__event_emitter__)

        if self.valves.STATUS:
            await emitter.emit(f"正在搜索: {query}")

        search_engine_url = self.valves.SEARXNG_ENGINE_API_BASE_URL

        params = {
            "q": query,
            "format": "json",
            "number_of_results": self.valves.RETURNED_SCRAPPED_PAGES_NO,
        }

        try:
            if self.valves.STATUS:
                await emitter.emit("正在向搜索引擎发送请求")
            resp = requests.get(
                search_engine_url, params=params, headers=self.headers, timeout=120
            )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            if self.valves.STATUS:
                await emitter.emit(f"返回了 {len(results)} 个搜索结果")

        except requests.exceptions.RequestException as e:
            if self.valves.STATUS:
                await emitter.emit(
                    status="error",
                    description=f"搜索时出错: {str(e)}",
                    done=True,
                )
            return json.dumps({"error": str(e)})

        results_json = []
        if results:
            if self.valves.STATUS:
                await emitter.emit("正在处理搜索结果")

            try:
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    futures = [
                        executor.submit(
                            functions.process_search_result, result, self.valves
                        )
                        for result in results
                    ]

                    processed_count = 0
                    for future in concurrent.futures.as_completed(futures):
                        result_json = future.result()
                        if result_json:
                            try:
                                results_json.append(result_json)
                                processed_count += 1
                                if self.valves.STATUS:
                                    await emitter.emit(
                                        f"处理页面 {processed_count}/{len(results)}",
                                    )
                            except (TypeError, ValueError, Exception) as e:
                                print(f"处理时出错: {str(e)}")
                                continue
                        if len(results_json) >= self.valves.RETURNED_SCRAPPED_PAGES_NO:
                            break

            except BaseException as e:
                if self.valves.STATUS:
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

        urls = []
        for result in results_json:
            urls.append(result["url"])

        if self.valves.STATUS:
            await emitter.emit(
                status="complete",
                description=f"搜索到 {len(results_json)} 个结果",
                done=True,
                action="web_search",
                urls=urls,
            )

        return json.dumps(results_json, indent=4, ensure_ascii=False)

    async def get_website(
        self, url: str, __event_emitter__: Callable[[dict], Any] | None = None
    ) -> str:
        """
        打开输入的网站并获取其内容

        :params url: 需要打开的网站

        :return: The content of the website in json format.
        """
        functions = HelpFunctions()
        emitter = EventEmitter(__event_emitter__)
        if self.valves.STATUS:
            await emitter.emit(f"正在从URL获取内容: {url}")

        results_json = []

        if url.strip() == "":
            return ""

        result_site = functions.fetch_and_process_page(url, self.valves)
        results_json.append(result_site)

        if (
            self.valves.CITATION_LINKS
            and "content" in result_site
            and __event_emitter__
        ):
            await __event_emitter__(
                {
                    "type": "citation",
                    "data": {
                        "document": [result_site["content"]],
                        "metadata": [{"source": result_site["url"]}],
                        "source": {"name": result_site["title"]},
                    },
                }
            )
        if self.valves.STATUS:
            await emitter.emit(
                status="complete", description="已成功检索和处理网站内容", done=True
            )
        return json.dumps(results_json, indent=4, ensure_ascii=False)
