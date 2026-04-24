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
    """将PIL Image转为base64字符串（JPEG压缩以控制大小）。"""
    buffer = io.BytesIO()
    if image.width > 1600:
        ratio = 1600 / image.width
        image = image.resize((1600, int(image.height * ratio)))
    image.save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode("utf-8")


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
    优先使用官方layout_parsing API，失败时回退到chat completions。

    Args:
        image: PIL Image 对象

    Returns:
        识别出的文字内容
    """
    model = _ocr_config.get("model", "glm-ocr")
    b64 = _image_to_base64(image)
    data_url = f"data:image/jpeg;base64,{b64}"

    # glm-ocr 使用官方 layout_parsing 端点
    if model == "glm-ocr":
        try:
            return _layout_parsing(data_url)
        except Exception as e:
            logger.warning("GLM-OCR layout_parsing 调用失败，回退到 chat completions: %s", e)
            return _ocr_with_chat_completions(image, model="glm-4v-flash")

    # glm-4v-flash / glm-4v-plus 等视觉模型使用 chat completions
    return _ocr_with_chat_completions(image, model=model)


def ocr_pdf(pdf_path: Path) -> str:
    """
    将PDF转为图片后逐页OCR识别。

    Args:
        pdf_path: PDF文件路径

    Returns:
        所有页面的文字拼接结果
    """
    images = convert_from_path(str(pdf_path), dpi=200)
    logger.info("PDF转图片完成: %s，共 %d 页", pdf_path.name, len(images))

    all_texts = []
    for i, image in enumerate(images, 1):
        logger.info("OCR识别第 %d/%d 页: %s", i, len(images), pdf_path.name)
        text = ocr_image(image)
        if text:
            all_texts.append(text)

    return "\n\n".join(all_texts)
