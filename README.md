# web_search

## 简介

`web_search` 是一个使用 SearXNG 搜索并爬取网页的搜素工具，它还有用一个用于爬取指定网页的函数。它能够从搜索引擎中获取搜索结果，并处理这些结果以提取所需的信息。此工具使用jina-reader读取网页。并使用了线程池发送请求

## 功能

- 使用 SearXNG 搜索引擎进行网页搜素
- 爬取和处理搜索结果的页面内容
- 支持忽略特定网站的结果
- 截断长文本以适应特定的字数限制
- 提取和格式化网页标题、内容和摘要
- 实验性RAG

## 使用方法

打开/workspace/tools/create，粘贴web-search.py内的内容

## 来源

此工具的原始代码来自[此处](https://openwebui.com/t/constliakos/web_search)，加入了使用jina-reader提取内容和折叠的搜索结果标题等新功能后发布

## 贡献

如果你有任何建议或改进意见，欢迎通过 GitHub 提交 Pull Request 或创建 Issue 与我们分享。感谢你的贡献！
