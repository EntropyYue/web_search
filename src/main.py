"""
title: Web Search
author: EntropyYue
funding_url: https://github.com/EntropyYue/web_search
version: 10.3
license: MIT
"""

import asyncio
import json
from collections.abc import Callable
from typing import Any

from aiohttp import ClientSession, ClientTimeout
from pydantic import BaseModel, Field

from utils import BM25Retriever, EventEmitter, LoadResult, SearchEngine, WebLoader


class Tools:
    class Valves(BaseModel):
        SEARXNG_ENGINE_API_BASE_URL: str = Field(
            default="https://example.com/search", description="搜索引擎的基础URL"
        )
        IGNORED_WEBSITES: str = Field(
            default="", description="以逗号分隔的要忽略的网站列表"
        )
        MAX_SEARCH_RESULTS: int = Field(
            default=3, description="单个关键词要返回的结果数"
        )
        MAX_PROCESSED_RESULTS: int = Field(default=10, description="要处理的最大结果数")
        SEARCH_PAGE_TOKENS_LIMIT: int = Field(
            default=2000, description="搜索结果每页的限制Token数"
        )
        GET_WEBSITE_TOKENS_LIMIT: int = Field(
            default=5000, description="获取网站的限制Token数"
        )
        BM25_RERANK_TOP_K: int = Field(
            default=5, description="使用BM25重新排序时的Top-K"
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
        queries: list[str],
        __event_emitter__: Callable[[dict], Any] | None = None,
    ) -> str:
        """
        搜索网络并获取相关页面的内容，搜索未知知识、新闻、信息、公共联系信息、天气等

        :params queries: 搜索中使用的关键词列表

        :return: 网站内容的json格式
        """
        loader = WebLoader(
            ignore_websites=self.valves.IGNORED_WEBSITES,
            headers=self.headers,
            token_limit=self.valves.GET_WEBSITE_TOKENS_LIMIT,
        )
        emitter = EventEmitter(
            enable_status=self.valves.STATUS,
            enable_citation=self.valves.CITATION_LINKS,
            event_emitter=__event_emitter__,
        )
        search_engine = SearchEngine(
            url=self.valves.SEARXNG_ENGINE_API_BASE_URL,
            max_result=self.valves.MAX_SEARCH_RESULTS,
            headers=self.headers,
        )

        await emitter.status("Searching the web")

        await emitter.queries(queries)
        async with ClientSession(
            trust_env=self.valves.USE_ENV_PROXY, timeout=self.timeout
        ) as session:
            tasks = [
                asyncio.create_task(search_engine.search(query, session))
                for query in queries
            ]
            results: list[dict[str, str]] = []
            for done in asyncio.as_completed(tasks):
                try:
                    search_result = await done
                except Exception as e:
                    await emitter.status(
                        status="error",
                        description=f"搜索时出错: {str(e)}",
                        done=True,
                    )
                    search_result = {}

                if "results" in search_result:
                    results.extend(search_result["results"])
        if len(results) == 0:
            await emitter.status(
                status="error", description="未找到搜索结果", done=True
            )
            return json.dumps(
                {"error": "No search results found"}, indent=4, ensure_ascii=False
            )

        await emitter.urls([result.get("url", "") for result in results])

        results_json: list[LoadResult] = []
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
                except Exception:
                    continue

                if result_json:
                    results_json.append(result_json)

                if len(results_json) >= self.valves.MAX_PROCESSED_RESULTS:
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    break

            if len(results_json) == 0:
                await emitter.fetched(0)
                return json.dumps(
                    {"error": "No fetched results found"}, indent=4, ensure_ascii=False
                )

            await emitter.retrieval(queries)
            bm25_retriever = BM25Retriever(
                results_json, k=self.valves.BM25_RERANK_TOP_K
            )
            results_json = await bm25_retriever.ainvoke(" ".join(queries))

            for result in results_json:
                if result.text and result.metadata:
                    await emitter.citation(
                        document=[result.text],
                        metadata=[{"source": result.metadata.url}],
                        source={"name": result.metadata.title},
                    )

        await emitter.fetched(len(results_json))

        return json.dumps(
            [r.to_dict() for r in results_json], indent=4, ensure_ascii=False
        )

    async def get_website(
        self, urls: list[str], __event_emitter__: Callable[[dict], Any] | None = None
    ) -> str:
        """
        打开输入的网站并获取其内容

        :params urls: 需要打开的网站列表

        :return: 网站内容的json格式
        """
        loader = WebLoader(
            ignore_websites=self.valves.IGNORED_WEBSITES,
            token_limit=self.valves.GET_WEBSITE_TOKENS_LIMIT,
            headers=self.headers,
        )
        emitter = EventEmitter(
            enable_status=self.valves.STATUS,
            enable_citation=self.valves.CITATION_LINKS,
            event_emitter=__event_emitter__,
        )

        await emitter.status("Searching the web")

        await emitter.queries(urls)

        results_json: list[LoadResult] = []

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
                except Exception:
                    continue

                if result_site:
                    results_json.append(result_site)

                if result_site.text and result_site.metadata:
                    await emitter.citation(
                        document=[result_site.text],
                        metadata=[{"source": result_site.metadata.url}],
                        source={"name": result_site.metadata.url},
                    )

        await emitter.fetched(len(results_json))

        return json.dumps(
            [r.to_dict() for r in results_json], indent=4, ensure_ascii=False
        )
