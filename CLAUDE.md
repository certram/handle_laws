# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Legal document automation system for Chinese property preservation cases (财产保全). Extracts case information from PDF files using AI, stores structured data in YAML, and generates court documents (协助执行通知书, 保全裁定书) from Word templates.

## Commands

```bash
# CLI (main interface)
python3 main.py                        # Process all cases in original_files/
python3 main.py --new                  # Only process new (untracked) cases
python3 main.py -f                     # Force full pipeline for all cases (re-extract even if YAML exists)
python3 main.py <output_subdir_name>   # Regenerate docx from existing YAML (e.g. "case_two")
python3 main.py --clean                # Delete docx files, regenerate from YAML

# Template building (run when original templates change)
python3 build_templates.py             # Build bank/alipay/tenpay/equity templates from originals
python3 build_extra_templates.py       # Build ruling/dossier templates from originals

# Web interface
python3 run_web.py                     # Start Flask web app
```

No test suite exists in this project.

## Architecture

### Data Flow

```
PDF files (original_files/<case>/)
  → pdf_extractor.py (text/OCR extraction)
  → ai_extractor.py (AI structured extraction via DashScope/Qwen-Long)
  → yaml_generator.py (YAML output)
  → doc_generator.py (Word document generation from templates)
  → outputs/<case>/*.docx + *.yaml
```

### Key Modules

- **`main.py`** — CLI entry point. Tracks processed cases in `.processed.json`. The `--force` flag bypasses YAML caching to re-run AI extraction. Passing an `outputs/` subdirectory name regenerates docx from existing YAML only.

- **`pdf_extractor.py`** — Extracts text from PDFs. Tries pdfplumber first (text PDFs), falls back to ocrmypdf OCR (scanned/image PDFs). Returns `{filename: text}` dict.

- **`ai_extractor.py`** — Four AI functions:
  - `extract_case_info()` — Main extraction: all PDF texts → structured case JSON (cross-document consolidation)
  - `extract_bank_name()` — Extracts bank branch name from property clue text
  - `extract_alipay_account()` — Extracts Alipay account (phone number) from clue text
  - `extract_tenpay_account()` — Extracts WeChat ID (wxid_) from clue text

- **`config.py`** — Loads `settings.yaml` for API credentials. Defines the JSON schema for case extraction and the system/user prompts. Schema covers: 案件基础信息, 原告, 被告, 保全信息 (财产线索), 担保信息. Individual parties require: 姓名, 性别, 出生日期, 身份证号码, 住址, 民族.

- **`doc_generator.py`** — Two generation paths:
  - **Assist notices** (协助执行通知书): Uses `docxtpl` (Jinja2) to render templates per property clue. AI extraction called at generation time for bank name, alipay account, tenpay account.
  - **Ruling** (保全裁定书): Uses `python-docx` directly (not docxtpl) to handle dynamic multi-paragraph defendant insertion via `deepcopy`. Template has `{{ defendants_block }}` marker replaced with N defendant paragraphs.

- **`build_templates.py`** — Converts `original_templates/` to jinja2 `templates/` for bank/alipay/tenpay/equity. Preserves original formatting (fonts, sizes, spacing) via cross-run text replacement.

- **`build_extra_templates.py`** — Builds ruling.docx and dossier.docx from original court templates. Uses content-based paragraph finding (not index-based) to avoid offset issues after deletions.

### Template System

Templates in `templates/` are Word files with Jinja2 variables. Property clue types map to templates:

| Clue Type Keyword | Template File |
|---|---|
| 银行/银行账户 | bank.docx |
| 支付宝 | alipay.docx |
| 财付通 | tenpay.docx |
| 房产 | property.docx |
| 股权 | equity.docx |
| 车辆 | vehicle.docx |

Template fonts (from original court templates):
- 标题: 方正小标宋简体 22pt
- 正文: 仿宋/仿宋_GB2312 16pt
- 财付通账号字段: 方正黑体_GBK

### Case Data Schema (YAML)

```yaml
案件基础信息:
  案号: (2026)粤0305民初7226号   # parsed for year and case number
  案由: 民间借贷纠纷
  立案法院: 深圳市南山区人民法院
  承办法官: 毛法官
原告/被告:    # list of parties
  - 类型: 个人    # or 公司
    # 个人字段: 姓名, 性别, 出生日期(YYYY-MM-DD), 身份证号码, 住址, 民族
    # 公司字段: 全称, 统一社会信用代码, 法定代表人, 所在地
保全信息:
  申请保全总金额: "1083005.56"
  财产线索:       # each clue → one doc
    - 类型: 银行账户
      详细内容: ...
      归属地: 深圳
担保信息:
  担保人名称: 阳光财产保险股份有限公司深圳市分公司
```

### Important Implementation Details

- **Ruling document** (`_generate_ruling`): Cannot use docxtpl for defendant paragraphs because `{{ }}` can't create new paragraphs. Instead uses python-docx with `deepcopy` of paragraph XML elements, preserving formatting (JUSTIFY, line_spacing=355600, first_indent=401320).
- **Ethnicity handling**: AI extracts `汉` from ID cards, but ruling document appends `族` to produce `汉族` if not already present.
- **Chinese dates**: `_date_to_chinese()` converts dates to format like `二〇二六年四月十四日` (〇 is Chinese zero U+3007).
- **Fixed values in templates**: 联系人、联系电话、本院地址 are fixed in the main body of assist notices. Only the receipt (回执) section has empty fields. Actual values are hardcoded in `doc_generator.py`.
- **Fixed values in ruling**: 审判员 and 书记员 names are fixed, never templated. Actual values are hardcoded in `doc_generator.py`.

### Web Interface

Flask app in `web/` with routes for case management, document editing, and template management. Entry point: `run_web.py`.
