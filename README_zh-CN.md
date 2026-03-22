# 引用查验工具 (Citation Bullshit Detector)

[English](README.md)

一个自动化的学术论文引用验证工具。解析 LaTeX 论文，在 Google Scholar 上搜索被引文献，下载 PDF，然后使用大语言模型评估每条引用是否真正支撑了正文中的论述。

## 工作流程

```
LaTeX (.tex) + 参考文献 (.bib)
        |
        v  [core/parser.py]
  引用记录 (cite_key, 元数据, 正文上下文)
        |
        v  [core/downloader.py]
  Google Scholar 搜索 (ScrapingDog / SerpAPI)
    |-- 有 PDF        --> 下载到 data/pdfs/
    |-- 无 PDF        --> 保存摘要作为替代
    '-- 未找到        --> 仅基于元数据验证
        |
        v  [utils/pdf_extractor.py]
  PDF 解析 --> 文本 (FireRed-OCR / MinerU / PyMuPDF)
        |
        v  [core/rag_engine.py]
  TF-IDF 检索 --> 相关段落
        |
        v  [core/llm_analyzer.py]
  LLM 验证 --> 支撑等级 + 引文原文
        |
        v  [main.py]
  报告 (Markdown + JSON) --> data/output/
```

## 功能特性

- **LaTeX/BibTeX 解析** -- 提取所有 `\upcite{}` 引用及其周围的正文上下文
- **Google Scholar 搜索** -- 通过 ScrapingDog 和 SerpAPI，自动轮换 Key 并跟踪用量
- **智能缓存** -- 搜索结果、摘要和 PDF 均缓存到本地，最大程度减少 API 调用
- **3 种 PDF 解析器** -- FireRed-OCR（VLM，默认）、MinerU、PyMuPDF，通过配置切换
- **3 种验证模式** -- 全文模式、摘要模式、元数据模式，根据可用数据自动选择
- **结构化报告** -- 每条引用的支撑等级、文献原文引句、解释说明

## 项目结构

```
cite_bullshit_detect/
├── config/
│   ├── settings.py            # 全局配置，加载 .env
│   └── prompt_templates.py    # LLM 提示词模板（3 种模式）
├── core/
│   ├── parser.py              # LaTeX/BibTeX 解析器
│   ├── downloader.py          # Scholar 搜索 + PDF 下载 + 缓存
│   ├── rag_engine.py          # TF-IDF 段落检索
│   └── llm_analyzer.py        # LLM 引用验证
├── utils/
│   ├── logger.py              # 日志模块
│   ├── text_cleaner.py        # LaTeX 命令清洗、中文分句
│   └── pdf_extractor.py       # PDF 解析器 (FireRed-OCR / MinerU / PyMuPDF)
├── data/
│   ├── input/                 # .tex 和 .bib 文件
│   ├── pdfs/                  # 下载的 PDF + 缓存文件
│   └── output/                # 生成的报告
├── main.py                    # CLI 入口
├── requirements.txt
└── .env.example
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

如使用 FireRed-OCR（默认 PDF 解析器），需要 GPU 环境，模型会在首次运行时自动从 HuggingFace 下载。

### 2. 配置

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 API Key：

| 变量 | 说明 |
|---|---|
| `OPENAI_API_KEY` | OpenAI 兼容 API Key（支持 OpenRouter 等） |
| `OPENAI_BASE_URL` | API 端点地址 |
| `LLM_MODEL` | 模型名称（如 `gpt-4o-mini`） |
| `SCRAPINGDOG_KEYS` | ScrapingDog API Key，多个用逗号分隔 |
| `SERPAPI_KEYS` | SerpAPI Key，多个用逗号分隔 |
| `PDF_PARSER` | `firered`（默认）、`mineru` 或 `pymupdf` |

### 3. 准备输入

将待检测的 LaTeX 论文文件（`.tex`）和参考文献（`.bib`）放入 `data/input/` 目录。

### 4. 运行

```bash
# 完整流程
python main.py

# 跳过 PDF 下载（使用已有 PDF 和缓存）
python main.py --skip-download

# 使用其他 PDF 解析器
python main.py --pdf-parser pymupdf

# 自定义输出路径
python main.py --output my_report.md
```

### 5. 查看结果

- Markdown 报告：`data/output/report.md`
- JSON 结果：`data/output/report.json`

## 验证等级

| 等级 | 含义 |
|---|---|
| `STRONGLY_SUPPORTS` | 文献明确支撑正文论述 |
| `SUPPORTS` | 文献相关且具有支撑性 |
| `WEAKLY_SUPPORTS` | 相关性较弱 |
| `UNRELATED` | 文献与正文论述无关 |
| `CONTRADICTS` | 文献与正文论述矛盾 |
| `CANNOT_VERIFY` | 数据不足，无法判断 |

## 缓存机制

所有 API 结果均缓存在 `data/pdfs/` 目录下，避免重复请求：

- `scholar_cache.json` -- Google Scholar 搜索结果
- `abstracts.json` -- 论文摘要
- `*.pdf` -- 下载的 PDF 文件

再次运行会自动复用缓存数据。如需强制重新搜索，删除对应缓存文件即可。

## License

MIT
