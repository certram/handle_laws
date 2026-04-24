# Handle Laws - 法律案件材料信息提取与文书生成工具

从法律案件的PDF材料中自动提取关键信息（原告被告、案号、财产线索等），并生成对应的协助执行通知书（Word文档）。

## 功能概述

1. **PDF文本提取** - 自动识别文本型PDF和扫描件（图片型PDF），扫描件自动启用OCR识别
2. **AI跨文档信息提取** - 将一个案件的所有PDF内容合并后交给AI，智能交叉提取完整的案件信息，生成结构化YAML文件
3. **协助执行通知书生成** - 根据财产线索类型，自动匹配模板生成对应的协助执行通知书（Word文档），每条财产线索生成一份

## 目录结构

```
handle_laws/
├── main.py              # 主入口，运行这个文件启动处理
├── delete_docs.py       # 按类型删除协助执行通知书
├── config.py            # 配置加载（从settings.yaml读取）
├── settings.yaml        # 配置文件（API密钥、模型、文件命名、删除配置）
├── pdf_extractor.py     # PDF文本提取模块（pdfplumber + ocrmypdf OCR兜底）
├── ai_extractor.py      # AI结构化信息提取模块（Qwen-Long）
├── yaml_generator.py    # YAML文件生成模块
├── doc_generator.py     # Word文书生成模块（协助执行通知书 + 裁定书 + 保全卷）
├── requirements.txt     # Python依赖列表
├── templates/           # Word模板目录
│   ├── bank.docx        # 银行账户 - 协助冻结存款通知书
│   ├── alipay.docx      # 支付宝 - 协助冻结存款通知书
│   ├── tenpay.docx      # 财付通 - 协助冻结存款通知书
│   ├── property.docx    # 房产 - 协助执行通知书
│   ├── equity.docx      # 股权 - 协助执行通知书
│   ├── vehicle.docx     # 车辆 - 协助执行通知书
│   ├── ruling.docx      # 保全裁定书模板
│   └── dossier.docx     # 保全卷模板
├── original_files/      # 【输入】案件PDF材料放这里
├── outputs/             # 【输出】生成的YAML和Word文件
└── regenerate.json      # 【可选】批量重新生成时，填入需要重新生成的案号
```

## 环境准备

### 1. Python版本

Python 3.10 及以上

### 2. 安装Python依赖

```bash
pip install -r requirements.txt
```

依赖包说明：

| 包名 | 用途 |
|------|------|
| pdfplumber | 文本型PDF文字提取 |
| ocrmypdf | 扫描件PDF的OCR识别 |
| openai | 调用通义千问API（OpenAI兼容接口） |
| pyyaml | 读写YAML配置文件 |
| docxtpl | Word模板渲染（Jinja2语法） |

### 3. 安装Tesseract OCR（处理扫描件PDF需要）

```bash
# macOS
brew install tesseract tesseract-lang

# Ubuntu/Debian
sudo apt install tesseract-ocr tesseract-ocr-chi-sim
```

> 如果案件PDF全部是文本型（非扫描件），可以不安装Tesseract。

### 4. 配置API密钥

编辑项目根目录下的 `settings.yaml`，填入你的 API Key 并选择模型：

```yaml
# AI 模型配置（used: true 的模型会被使用，只能有一个）
models:
  - name: "qwen-long"
    api_key: "你的API Key"
    base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
    model: "qwen-long"
    used: true

  # 取消注释即可使用，将上面的 used 改为 false，下面的改为 true
  # - name: "deepseek"
  #   api_key: "你的DeepSeek API Key"
  #   base_url: "https://api.deepseek.com/v1"
  #   model: "deepseek-chat"
  #   used: false

naming:
  civil_first: "26民初"

delete:
  - "支付宝"
  - "财付通"
  - "银行"
```

- `models`：模型列表，**只能有一个** `used: true`，程序启动时会校验
- `name`：模型备注名（仅用于区分，不影响调用）
- `api_key` / `base_url` / `model`：OpenAI 兼容接口的三要素
- `civil_first`：保全卷和裁定书文件名的前缀，如 `26民初13074保全卷.docx`
- `delete`：`delete_docs.py` 默认删除的协助执行通知书类型，支持的关键词：支付宝、财付通、银行、房产、股权、车辆。命令行参数可覆盖此配置

支持的模型示例（只要提供 OpenAI 兼容接口即可）：

| 提供商 | base_url | model | 上下文窗口 |
|--------|----------|-------|-----------|
| 阿里云 DashScope | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-long` | 1M |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` | 128K |
| 月之暗面 | `https://api.moonshot.cn/v1` | `moonshot-v1-128k` | 128K |
| MiniMax | `https://api.minimax.chat/v1` | `MiniMax-M1` | 1M |

> 注意：切换模型时需确认上下文窗口是否足够容纳案件的全部 PDF 文本。qwen-long 和 MiniMax-M1 支持 1M tokens，适合多文件案件。

API Key 获取方式：登录 [阿里云DashScope控制台](https://dashscope.console.aliyun.com/) 创建。

## 使用方法

> **YAML 缓存机制**：程序处理案件时，如果 `outputs/` 下对应的案件目录已有 YAML 文件，会直接复用 YAML 生成文书，跳过 PDF 提取和 AI 调用。只有加 `-f` / `--force` 参数才会强制重新走完整流程（PDF → AI → YAML → 文书）。

### 单个案件

将案件的所有PDF材料放入 `original_files/` 文件夹，然后运行：

```bash
python main.py
```

输出结果在 `outputs/` 目录下，包含：

- 一个YAML文件：提取的案件结构化信息
- 若干Word文件：根据财产线索生成的协助执行通知书

### 多个案件（批量处理）

在 `original_files/` 下为每个案件创建一个子文件夹：

```
original_files/
├── 案件A/
│   ├── 保函.pdf
│   ├── 原告身份证明.pdf
│   ├── 被告身份证明.pdf
│   └── 财产保全申请书.pdf
├── 案件B/
│   ├── 保函.pdf
│   ├── 原告身份证明.pdf
│   └── ...
└── 案件C/
    └── ...
```

运行同样的命令：

```bash
python main.py
```

程序会自动检测到多个子文件夹，逐个处理每个案件。输出结构如下：

```
outputs/
├── （2026）粤0305民初13074号-20260323/
│   ├── 2026粤0305民初13074号_20260416.yaml
│   ├── 26民初13074保全卷.docx
│   ├── 26民初13074保全裁定书（260416）.docx
│   ├── 协助执行通知书（查封深圳房产）.docx
│   ├── 协助执行通知书（查封车辆）.docx
│   ├── 协助执行通知书（银行8389）.docx
│   └── ...
└── 其他案件/
    └── ...
```

### 只处理新增案件（--new）

`--new` 模式下，程序只处理 `.processed.json` 中未记录的案件，已处理的跳过：

```bash
python main.py --new
```

### 强制重新提取（-f / --force）

默认情况下，如果输出目录已有 YAML 文件，会直接复用 YAML 重新生成 Word 文档，跳过 PDF 提取和 AI 调用。加 `-f` 可强制走完整流程（PDF → AI → YAML → Word）：

```bash
python main.py -f                              # 强制重新处理所有案件
python main.py -f /path/to/specific/case       # 强制重新处理指定案件
#如下举具体例子：
python3 main.py -f "original_files/（2026）粤0305民初12038号-20260323"
# 上述命令含义：针对（2026）粤0305民初12038号-20260323这个案件，会重新走完完整流程（PDF → AI → YAML → Word）
```

### 从已有 YAML 重新生成文书

如果只修改了模板或生成逻辑，不想重新调用 AI，可以直接指定 outputs 子目录名，从已有 YAML 重新生成 Word 文档：

```bash
python main.py "（2026）粤0305民初13074号-20260323"
```

### 清理旧文档后重新生成（-c / --clean）

删除已有 docx 文件，然后复用 YAML 重新生成所有文书（不重新走 PDF 提取和 AI 调用）。

```bash
python main.py -c                              # 清理 outputs/ 下所有案件的 docx，然后全部重新生成
python main.py -c "案件目录名"                  # 只清理指定案件的 docx 并重新生成
```

### 民事模式（--civil）

只生成外勤类协助执行通知书，跳过鹰眼类和支付宝。裁定书和保全卷不受影响，照常生成。

跳过规则：

- **鹰眼类**：23家鹰眼银行账户、深圳市内房产/股权/车辆 → 跳过
- **支付宝** → 跳过
- **财付通、外勤银行、深圳市外房产/股权/车辆** → 正常生成

```bash
python main.py --civil                         # 民事模式处理所有案件
python main.py --new --civil                   # 民事模式只处理新案件
python main.py -c --civil "案件目录名"           # 民事模式清理并重新生成指定案件
python main.py -f --civil                      # 民事模式强制重新走完整流程
python main.py --civil /path/to/pdf/folder     # 民事模式处理指定目录下的案件
```

> 不加 `--civil` 时，默认所有财产线索都会生成协助执行通知书。

### 批量从 YAML 重新生成（--regen）

适用于人工审查完多个案件后，部分案件的 YAML 被手动修正过，需要批量重新生成 Word 文书的场景。

**步骤1：** 在项目根目录创建 `regenerate.json`，填入需要重新生成的案号（只写数字即可）：

```json
[12038, 13324]
```

**步骤2：** 运行：

```bash
python main.py --regen
```

程序会用 `民初{案号}号` 正则匹配 `outputs/` 下的目录，找到后从已有 YAML 重新生成 docx（不会重新调用 PDF 提取和 AI）。

也支持与 `--civil` 组合：

```bash
python main.py --regen --civil
```

> 用完后可以删除 `regenerate.json`，不影响其他功能。

### 重置（-r / --reset）

清空 `outputs/` 和 `original_files/` 下所有子目录及文件，并删除 `.processed.json`，恢复到初始状态。`outputs/` 和 `original_files/` 目录本身保留。

```bash
python main.py -r
python main.py --reset
```

### 按类型删除协助执行通知书（delete_docs.py）

先生成全量文书后，再按类型选择性删除不需要的协助执行通知书。裁定书和保全卷不受影响。

关键词匹配文件名中的类型标识，支持的关键词：支付宝、财付通、银行、房产、股权、车辆。

**方式1：读取 `settings.yaml` 的 `delete` 配置**

```bash
python3 delete_docs.py
```

**方式2：命令行直接指定关键词（覆盖配置文件）**

```bash
python3 delete_docs.py 支付宝 财付通 银行    # 只删除这三种
python3 delete_docs.py 房产                   # 只删除房产类
```

**预览模式（不实际删除，只显示将被删除的文件）**

```bash
python3 delete_docs.py --dry-run
```

> 典型工作流：先用 `python main.py` 生成所有文书 → 用 `python3 delete_docs.py --dry-run` 预览 → 确认无误后 `python3 delete_docs.py` 执行删除。

### 指定输入目录

案件不一定要放在 `original_files/` 下，可以放在任意目录。直接传入案件文件夹的路径即可：

```bash
# 单个案件：指向案件文件夹本身
python3 main.py ~/codes/（2026）粤0305民初12038号-20260323

# 多个案件：如果 ~/codes/ 下有多个案件子文件夹，指向父目录即可，程序会自动扫描
python3 main.py ~/codes/
```

程序对传入路径的处理逻辑：
- 如果传入的是一个**有效目录路径**（如 `~/codes/某案件/`），直接以该目录作为输入，走完整流程（PDF → AI → YAML → Word）
- 如果传入的路径**不是有效目录**，但恰好是 `outputs/` 下的子目录名（如 `"（2026）粤0305民初12038号-20260323"`），则从已有 YAML 重新生成 Word 文档
- 目录名格式建议：`案号-日期`（如 `（2026）粤0305民初12038号-20260323`），程序会自动从目录名提取案号，优先级高于 AI 提取结果

```bash
# 常见用法示例
python3 main.py ~/Desktop/案件材料/（2026）粤0305民初12038号-20260323   # 处理指定案件
python3 main.py -f ~/Desktop/案件材料/（2026）粤0305民初12038号-20260323  # 强制重新处理指定案件
python3 main.py --civil ~/Desktop/案件材料/                                # 民事模式处理目录下所有案件
```

### 参数汇总

| 参数 | 说明 |
|------|------|
| `python main.py` | 处理 `original_files/` 下所有案件（已有 YAML 则复用） |
| `python main.py --new` | 只处理未记录的新案件 |
| `python main.py -f` | 强制重新走完整流程（PDF→AI→YAML→Word） |
| `python main.py -c` | 先清理旧 docx，再重新生成 |
| `python main.py --civil` | 民事模式：只生成外勤类通知书（跳过鹰眼和支付宝） |
| `python main.py -r` | 重置：清空 outputs/ 和 original_files/ |
| `python main.py --regen` | 从 regenerate.json 读取案号，批量从 YAML 重新生成 Word |
| `python main.py "目录名"` | 从 outputs 中已有 YAML 重新生成 Word |
| `python main.py /path/to/dir` | 指定输入目录处理 |
| `python main.py -w 3` | 3个线程并行处理案件（默认1） |

`--civil` 可与 `--new`、`-c`、`-f`、`--regen` 叠加使用。

### 多线程并发处理（--workers / -w）

批量处理案件时，可通过 `--workers` 指定并发数，多线程同时处理多个案件，显著缩短总耗时：

```bash
python main.py -w 3              # 3个线程并行处理所有案件
python main.py -w 5 --new        # 5个线程并行处理新案件
python main.py -w 3 -f           # 3个线程强制重新处理所有案件
python main.py -w 3 --civil      # 民事模式 + 并发
```

> 建议并发数 3-5。过高的并发可能触发 API 限流。默认 `--workers 1` 即单线程顺序处理，行为与之前一致。

## 输入要求

### PDF文件

每个案件文件夹中需要包含以下类型的PDF材料（文件名不限，程序会从所有文件中交叉提取信息）：

| 文件类型 | 说明 |
|---------|------|
| 财产保全申请书 | 包含案号、案由、原告被告信息、财产线索、保全金额等 |
| 电子保函/担保书 | 包含担保方式、担保人、担保金额等 |
| 原告身份证明 | 营业执照（公司）或身份证（个人） |
| 被告身份证明 | 同上 |

文件名不要求固定，程序会从所有PDF中综合提取信息。但如果文件命名能体现类型（如包含"原告"、"保函"等关键词），AI提取会更准确。

### 支持的当事人类型

- **公司**：提取全称、统一社会信用代码、法定代表人、所在地、联系方式
- **个人**：提取姓名、性别、出生日期、身份证号码、住址、民族（6项必要字段）

每个案件的原告和被告都可以有多个，混合类型也支持。

**个人字段校验与补全：**

| 字段 | AI提取 | 自动补全规则 |
|------|--------|-------------|
| 姓名 | 优先 | — |
| 性别 | 优先 | 为空或与身份证号不一致时，从身份证号第17位推导（奇数=男，偶数=女） |
| 出生日期 | 优先 | 为空或与身份证号不一致时，从身份证号第7-14位推导 |
| 身份证号码 | 优先 | 不满18位时触发二次AI提取 |
| 住址 | 优先 | — |
| 民族 | 优先 | 为空时默认"汉" |

**其他校验：**

- 统一社会信用代码不满18位时，触发二次AI提取
- 财产线索为空时，触发二次AI提取
- 银行账号为空但详细内容中包含长数字串时，正则回退提取

### 支持的财产线索类型

| 类型 | 生成的文书 | 文件命名规则 |
|------|-----------|-------------|
| 银行账户 | 协助冻结存款通知书（正文+回执） | 协助执行通知书（银行{尾号4位}）.docx，尾号相同加 -1, -2 |
| 支付宝 | 协助冻结存款通知书 | 协助执行通知书（支付宝）.docx，多个加中文序号（一、二...） |
| 财付通 | 协助冻结存款通知书 | 协助执行通知书（财付通）.docx，多个加中文序号 |
| 房产 | 协助执行通知书 | 协助执行通知书（查封{城市}房产）.docx，同城市多套加中文序号 |
| 股权 | 协助执行通知书 | 协助执行通知书（冻结股权）.docx，多个加中文序号 |
| 车辆 | 协助执行通知书 | 协助执行通知书（查封{城市}车辆）.docx，同城市多辆加中文序号 |

每案还会额外生成：

| 文书 | 文件命名规则 |
|------|-------------|
| 保全裁定书 | {civil_first}{案号数字}保全裁定书（{YYMMDD}）.docx |
| 保全卷 | {civil_first}{案号数字}保全卷.docx |

其中 `civil_first` 在 `settings.yaml` 中配置（默认 `26民初`），日期为处理当天的年月日6位数字。

## 输出说明

### YAML文件

包含案件的所有提取信息，结构如下：

```yaml
案件基础信息:
  案号: "(2025)粤0305民初42226号"
  案由: "买卖合同纠纷"
  立案法院: "深圳市南山区人民法院"
  承办法官: ""
  立案日期: ""

原告:
  - 类型: "公司"
    全称: "广州德通机电科技有限公司"
    统一社会信用代码: "91440101XX59FWW15R"
    法定代表人: "刘某"
    所在地: "广州市荔湾区站xxx号A座四层自编"
    联系方式: "13802993843"

被告:
  - 类型: "公司"
    全称: "深圳市建工集团股份有限公司"
    统一社会信用代码: "9144EYID192189548K"
    法定代表人: "张三"
    所在地: "深圳市南山区..."
    联系方式: "0755-83619888"

保全信息:
  申请保全总金额: "103530.02"
  财产线索:
    - 类型: "银行账户"
      详细内容: "开户行：中国建设银行...；账号：442015..."
      归属地: "深圳"

担保信息:
  担保方式: "保险公司担保"
  担保人名称: "浙商财产保险股份有限公司广东分公司"
  担保金额: "103530.02"
```

### Word文档

每个案件生成以下文书：

1. **保全裁定书**（每案1份）：`26民初13074保全裁定书（260416）.docx`
2. **保全卷**（每案1份）：`26民初13074保全卷.docx`，财产线索按鹰眼（深圳市内/鹰眼银行）和外勤分类排列
3. **协助执行通知书**（每条财产线索1份），按类型命名：
   - `协助执行通知书（银行8389）.docx` — 银行类，括号内为账号尾号4位
   - `协助执行通知书（查封深圳房产）.docx` — 房产类，括号内为城市+房产
   - `协助执行通知书（查封车辆）.docx` — 车辆类
   - `协助执行通知书（支付宝）.docx` — 支付宝类
   - `协助执行通知书（冻结股权）.docx` — 股权类

## 处理流程

```
PDF文件 → 文本提取(pdfplumber/OCR) → AI提取(DeepSeek/Qwen-Long) → 字段标准化
                                                                 → 银行账号正则回退
                                                                 → 统一社会信用代码/身份证号校验
                                                                 → 个人字段校验（性别/出生日期/民族）
                                                                 → 财产线索二次提取（为空时）
                                                                 → YAML文件
                                                                 → 保全裁定书（每案1份）
                                                                 → 保全卷（每案1份，鹰眼/外勤分类）
                                                                 → 协助执行通知书（每条线索1份）
```

1. 遍历案件文件夹中所有PDF文件
2. 文本型PDF用pdfplumber直接提取文字；扫描件自动启用ocrmypdf进行OCR
3. 所有PDF的文本合并后，一次性发送给AI模型，AI交叉引用多份文档提取完整信息
4. **字段标准化**：将AI输出的变体字段名映射为标准名称
5. **银行账号正则回退**：AI未提取银行账号时，从详细内容中用正则匹配10-23位数字
6. **统一社会信用代码校验**：不满18位触发二次AI提取
7. **身份证号码校验**：不满18位触发二次AI提取
8. **个人字段校验**：用身份证号校验性别和出生日期（不一致时以身份证号为准），民族为空默认"汉"
9. **财产线索二次提取**：线索为空时，触发专项AI提取
10. 生成结构化YAML文件保存提取结果
11. 根据案件数据生成保全裁定书（每案1份）
12. 根据案件数据生成保全卷（每案1份），财产线索按鹰眼/外勤分类：
    - **鹰眼**：23家鹰眼银行账户、深圳市内房产/股权/车辆
    - **外勤**：非鹰眼银行账户、深圳市外房产/股权/车辆、支付宝、财付通
13. 根据财产线索类型匹配Word模板，逐条生成协助执行通知书

## 常见问题

**Q: 扫描件PDF提取失败怎么办？**

确认已安装Tesseract OCR和中文语言包：

```bash
tesseract --list-langs  # 检查是否包含 chi_sim
```

**Q: AI提取的信息不完整或不准确？**

- 确认PDF文本提取是否正确（可以先单独运行 `pdf_extractor.py` 检查提取的文本）
- 确认API Key是否有效、余额是否充足
- 程序使用 `temperature=0` 以减少AI幻觉，但复杂案件仍可能有遗漏

**Q: 某个案件处理失败会影响其他案件吗？**

不会。批量处理时，单个案件出错会跳过并继续处理下一个，日志中会记录错误信息。

**Q: 联系人和法院地址字段为空？**

这些信息（承办法官、联系电话、法院地址）需要原始PDF中包含才能提取。如果PDF中没有，这些字段会留空，需要手动补充到生成的Word文档中。

## 注意事项

- 本工具提取的信息仅供参考，生成文书后请务必人工核对关键信息（尤其是金额、身份证号、银行账号等）
- `settings.yaml` 中包含API密钥，请勿将此文件提交到公开仓库
- 建议在 `.gitignore` 中添加 `outputs/`、`__pycache__/` 和 `settings.yaml`
