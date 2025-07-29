"""
title: Web Search
author: EntropyYue
funding_url: https://github.com/EntropyYue/web_search
version: 7.4
license: MIT
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any

from aiohttp import ClientError, ClientSession
from pydantic import BaseModel, Field

from utils import EventEmitter, HelpFunctions


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
        MAX_SEARCH_RESULTS: int = Field(
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
        functions = HelpFunctions(self.valves, self.headers)
        emitter = EventEmitter(self.valves, __event_emitter__)

        await emitter.status(f"正在搜索: {query}")

        search_engine_url = self.valves.SEARXNG_ENGINE_API_BASE_URL

        params = {
            "q": query,
            "format": "json",
            "number_of_results": self.valves.MAX_SEARCH_RESULTS,
        }

        try:
            await emitter.status("正在向搜索引擎发送请求")
            async with ClientSession() as session:
                resp = await session.get(
                    search_engine_url, params=params, headers=self.headers
                )
                resp.raise_for_status()
                data = await resp.json()

        except ClientError as e:
            await emitter.status(
                status="error",
                description=f"搜索时出错: {str(e)}",
                done=True,
            )
            return json.dumps({"error": str(e)})

        results = data.get("results", [])
        await emitter.status(f"返回了 {len(results)} 个搜索结果")

        results_json: list[dict[str, str]] = []
        if not results:
            return json.dumps(
                {"error": "No search results found"}, indent=4, ensure_ascii=False
            )

        await emitter.status("正在处理搜索结果")

        async with ClientSession() as session:
            tasks = [
                asyncio.create_task(functions.process_search_result(result, session))
                for result in results
            ]

            processed_count = 0
            while tasks and processed_count < len(results):
                try:
                    done, pending = await asyncio.wait(
                        tasks, return_when=asyncio.FIRST_COMPLETED
                    )
                except BaseException:
                    continue
                for task in done:
                    result_json = await task
                    if not result_json:
                        continue
                    results_json.append(result_json)
                    processed_count += 1
                    await emitter.status(
                        f"处理页面 {processed_count}/{self.valves.MAX_SEARCH_RESULTS} , 共 {len(results)} 个页面",
                    )
                    if len(results_json) >= self.valves.MAX_SEARCH_RESULTS:
                        for task in pending:
                            task.cancel()

            results_json = results_json[: self.valves.MAX_SEARCH_RESULTS]

            if not len(results_json):
                return json.dumps(
                    {"error": "No fetched results found"}, indent=4, ensure_ascii=False
                )

            for result in results_json:
                await emitter.citation(
                    document=[result["content"]],
                    metadata=[{"source": result["url"]}],
                    source={"name": result["title"]},
                )

        urls: list[str] = []
        for result in results_json:
            urls.append(result["url"])

        await emitter.status(
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
        functions = HelpFunctions(self.valves, self.headers)
        emitter = EventEmitter(self.valves, __event_emitter__)
        await emitter.status(f"正在从URL获取内容: {url}")

        results_json = []

        if url.strip() == "":
            return ""
        async with ClientSession() as session:
            result_site = await functions.fetch_and_process_page(url, session)
        results_json.append(result_site)

        if (
            result_site
            and self.valves.CITATION_LINKS
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
        await emitter.status(
            status="complete", description="已成功获取网站内容", done=True
        )
        return json.dumps(results_json, indent=4, ensure_ascii=False)
