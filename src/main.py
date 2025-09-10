"""
title: Web Search
author: EntropyYue
funding_url: https://github.com/EntropyYue/web_search
version: 9.1
license: MIT
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout
from pydantic import BaseModel, Field

from utils import EventEmitter, WebLoader


class Tools:
    class Valves(BaseModel):
        SEARXNG_ENGINE_API_BASE_URL: str = Field(
            default="https://example.com/search", description="搜索引擎的基础URL"
        )
        IGNORED_WEBSITES: str = Field(
            default="", description="以逗号分隔的要忽略的网站列表"
        )
        MAX_SEARCH_RESULTS: int = Field(default=3, description="要分析的搜索引擎结果数")
        SEARCH_PAGE_TOKENS_LIMIT: int = Field(
            default=2000, description="搜索结果每页的限制Token数"
        )
        GET_WEBSITE_TOKENS_LIMIT: int = Field(
            default=5000, description="获取网站的限制Token数"
        )
        USE_ENV_PROXY: bool = Field(default=False, description="使用环境变量中的代理")
        WEB_LOAD_TIMEOUT: int = Field(default=5, description="网页抓取超时时间 (秒)")
        CITATION_LINKS: bool = Field(
            default=False, description="发送带有链接的自定义引用"
        )
        STATUS: bool = Field(default=True, description="发送状态")

    def __init__(self):
        self.valves = self.Valves()
        self.timeout = ClientTimeout(total=self.valves.WEB_LOAD_TIMEOUT)
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
        loader = WebLoader(
            valves=self.valves,
            headers=self.headers,
            token_limit=self.valves.SEARCH_PAGE_TOKENS_LIMIT,
        )
        emitter = EventEmitter(self.valves, __event_emitter__)

        await emitter.status("Searching the web")

        await emitter.queries([query])

        search_engine_url = self.valves.SEARXNG_ENGINE_API_BASE_URL
        params = {"q": query, "format": "json"}

        try:
            async with (
                ClientSession(trust_env=self.valves.USE_ENV_PROXY) as session,
                session.get(
                    search_engine_url, params=params, headers=self.headers
                ) as resp,
            ):
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
        await emitter.urls([result.get("url", "") for result in results])

        results_json: list[dict[str, str]] = []
        if not results:
            return json.dumps(
                {"error": "No search results found"}, indent=4, ensure_ascii=False
            )

        async with ClientSession(
            trust_env=self.valves.USE_ENV_PROXY, timeout=self.timeout
        ) as session:
            tasks = [
                asyncio.create_task(loader.process_search_result(result, session))
                for result in results
            ]

            for done in asyncio.as_completed(tasks):
                try:
                    result_json = await done
                except BaseException:
                    continue
                if not result_json:
                    continue

                results_json.append(result_json)

                if len(results_json) >= self.valves.MAX_SEARCH_RESULTS:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    break

            results_json = results_json[: self.valves.MAX_SEARCH_RESULTS]

            if not len(results_json):
                await emitter.fetched(0)
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

        await emitter.fetched(len(results_json))

        return json.dumps(results_json, indent=4, ensure_ascii=False)

    async def get_website(
        self, urls: list[str], __event_emitter__: Callable[[dict], Any] | None = None
    ) -> str:
        """
        打开输入的网站并获取其内容

        :params urls: 需要打开的网站

        :return: The content of the website in json format.
        """
        loader = WebLoader(
            valves=self.valves,
            headers=self.headers,
            token_limit=self.valves.GET_WEBSITE_TOKENS_LIMIT,
        )
        emitter = EventEmitter(self.valves, __event_emitter__)

        await emitter.status("Searching the web")

        await emitter.queries(urls)

        results_json = []

        if urls == []:
            return ""
        async with ClientSession(
            trust_env=self.valves.USE_ENV_PROXY, timeout=self.timeout
        ) as session:
            tasks = [
                asyncio.create_task(loader.fetch_and_process_page(url, session))
                for url in urls
            ]
            for task in asyncio.as_completed(tasks):
                try:
                    result_site = await task
                except BaseException:
                    continue
                if not result_site:
                    continue
                results_json.append(result_site)

                if "content" in result_site:
                    await emitter.citation(
                        document=[result_site["content"]],
                        metadata=[{"source": result_site["url"]}],
                        source={"name": result_site["title"]},
                    )
        await emitter.urls([result.get("url", "") for result in results_json])

        await emitter.fetched(len(results_json))

        return json.dumps(results_json, indent=4, ensure_ascii=False)
