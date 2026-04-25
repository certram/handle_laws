"""智谱AI OCR模块 - 使用GLM-OCR官方API识别图片/PDF中的文字。"""

import base64
import io
import logging
from pathlib import Path

from pdf2image import convert_from_path
from zai import ZhipuAiClient
import yaml

logger = logging.getLogger(__name__)

# 加载配置
_settings_path = Path(__file__).parent / "settings.yaml"
with open(_settings_path, "r", encoding="utf-8") as f:
    _settings = yaml.safe_load(f)

_ocr_config = _settings.get("ocr", {})


def _get_client() -> ZhipuAiClient:
    """创建智谱AI客户端。"""
    api_key = _ocr_config.get("api_key", "")
    if not api_key:
        raise ValueError("settings.yaml 中 ocr.api_key 未配置")
    return ZhipuAiClient(api_key=api_key)


def _image_to_base64(image) -> str:
    """将PIL Image转为base64字符串。"""
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=95)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


def _image_to_base64_with_dpi(image, dpi: int) -> str:
    """将PIL Image按指定DPI等比缩放后转为base64字符串。"""
    ratio = dpi / 300
    resized = image.resize((int(image.width * ratio), int(image.height * ratio)))
    return _image_to_base64(resized)


def _layout_parsing(file_url: str) -> str:
    """
    调用智谱官方 layout_parsing API（GLM-OCR专用端点）。

    Args:
        file_url: 图片URL或base64 data URL

    Returns:
        识别出的文字内容
    """
    client = _get_client()
    response = client.layout_parsing.create(
        model="glm-ocr",
        file=file_url,
    )

    # SDK 返回 LayoutParsingResp 对象，直接取 md_results
    md = (response.md_results or "").strip()
    if md:
        return md

    # 兜底：拼接 layout_details 中各块的 content
    parts = []
    for page in (response.layout_details or []):
        for block in page:
            c = (block.get("content") or "").strip()
            if c:
                parts.append(c)
    if parts:
        return "\n\n".join(parts)

    return ""


def _ocr_with_chat_completions(image, model: str = "glm-4v-flash") -> str:
    """
    使用智谱GLM-4V系列模型（通过chat completions接口）识别图片中的文字。
    作为GLM-OCR的备用方案。

    Args:
        image: PIL Image 对象
        model: 模型名称

    Returns:
        识别出的文字内容
    """
    from openai import OpenAI

    api_key = _ocr_config.get("api_key", "")
    client = OpenAI(
        api_key=api_key,
        base_url="https://open.bigmodel.cn/api/paas/v4/",
    )

    b64 = _image_to_base64(image)

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "请识别这张图片中的所有文字，按原文排版原样输出。只输出识别到的文字，不要添加任何解释。",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                        },
                    },
                ],
            }
        ],
    )

    return resp.choices[0].message.content.strip()


def ocr_image(image) -> str:
    """
    使用智谱GLM-OCR识别单张图片中的文字。
    先用原始DPI=300尝试，图片过大时逐步递减DPI（每次-20）重试。

    Args:
        image: PIL Image 对象

    Returns:
        识别出的文字内容
    """
    model = _ocr_config.get("model", "glm-ocr")

    if model == "glm-ocr":
        # 先用原始DPI=300尝试
        b64 = _image_to_base64(image)
        data_url = f"data:image/jpeg;base64,{b64}"
        try:
            return _layout_parsing(data_url)
        except Exception as e:
            err_msg = str(e)
            if "文件大小限制" in err_msg or "1214" in err_msg:
                # 图片过大，逐步递减DPI重试
                for dpi in range(280, 100, -20):
                    b64 = _image_to_base64_with_dpi(image, dpi)
                    img_size = len(base64.b64decode(b64))
                    if img_size > 10 * 1024 * 1024:
                        logger.info("DPI=%d 仍然过大 (%.1fMB)，继续降低", dpi, img_size / 1024 / 1024)
                        continue
                    logger.info("图片过大，降低至 DPI=%d (%.1fMB) 重试", dpi, img_size / 1024 / 1024)
                    data_url = f"data:image/jpeg;base64,{b64}"
                    try:
                        return _layout_parsing(data_url)
                    except Exception as retry_e:
                        logger.warning("DPI=%d 重试失败: %s", dpi, retry_e)
                        continue
                logger.warning("所有DPI均失败，回退到 chat completions")
            else:
                logger.warning("GLM-OCR layout_parsing 调用失败，回退到 chat completions: %s", e)
            return _ocr_with_chat_completions(image, model="glm-4v-flash")

    # glm-4v-flash / glm-4v-plus 等视觉模型使用 chat completions
    return _ocr_with_chat_completions(image, model=model)


def _select_key_pages(pdf_path: Path, total_pages: int) -> list[int] | None:
    """
    为大型保函PDF智能选页：仅OCR前5页 + 财产线索页。

    通过pdfplumber快速扫描页面文本，找到包含财产线索关键词的页面。
    如果pdfplumber无法提取文本（扫描件），返回None表示处理全部页面。

    Returns:
        需要OCR的页面索引列表（0-based），或None表示处理全部页面。
    """
    import pdfplumber

    key_pages = set(range(min(5, total_pages)))  # 前5页

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i in range(5, total_pages):
                text = (pdf.pages[i].extract_text() or "")
                if any(kw in text for kw in [
                    "财产线索", "银行账号", "开户银行", "账户",
                    "不动产", "微信号", "支付宝", "财付通",
                ]):
                    key_pages.add(i)
                    logger.info("pdfplumber发现财产线索页: 第%d页", i + 1)
    except Exception:
        logger.info("pdfplumber扫描失败，将处理全部页面")
        return None

    # 如果没找到额外的财产线索页，可能是扫描件，返回None处理全部
    if len(key_pages) <= min(5, total_pages) and total_pages > 5:
        logger.info("pdfplumber未发现额外财产线索页（可能是扫描件），将处理全部页面")
        return None

    return sorted(key_pages)


def ocr_pdf(pdf_path: Path) -> str:
    """
    将PDF转为图片后逐页OCR识别。
    对于压缩后总大小超过10MB的保函PDF，智能选页：仅OCR前5页+财产线索页。

    Args:
        pdf_path: PDF文件路径

    Returns:
        所有页面的文字拼接结果
    """
    images = convert_from_path(str(pdf_path), dpi=300)
    total = len(images)
    logger.info("PDF转图片完成: %s，共 %d 页", pdf_path.name, total)

    # 判断是否为大型保函，启用智能选页
    is_guarantee = "担保函" in pdf_path.name or "保函" in pdf_path.name

    if is_guarantee and total > 5:
        # 计算压缩后总大小
        total_size = 0
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=95)
            total_size += buf.tell()

        total_size_mb = total_size / 1024 / 1024
        logger.info("保函压缩后总大小: %.1fMB (%d页)", total_size_mb, total)

        if total_size_mb > 10:
            selected = _select_key_pages(pdf_path, total)
            if selected is not None:
                logger.info("大型保函 (%.1fMB, %d页)，智能选页: 第 %s 页",
                            total_size_mb, total, [p + 1 for p in selected])
                pages_to_ocr = selected
            else:
                pages_to_ocr = list(range(total))
        else:
            pages_to_ocr = list(range(total))
    else:
        pages_to_ocr = list(range(total))

    all_texts = []
    for i in pages_to_ocr:
        logger.info("OCR识别第 %d/%d 页: %s", i + 1, total, pdf_path.name)
        text = ocr_image(images[i])
        if text:
            all_texts.append(text)

    return "\n\n".join(all_texts)
