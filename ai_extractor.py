import json
import logging
import os

from openai import OpenAI

from config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_URL,
    MODEL_NAME,
    SCHEMA_JSON_STR,
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
)

logger = logging.getLogger(__name__)

client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_BASE_URL,
)


def _build_documents_text(all_texts: dict[str, str]) -> str:
    """将所有PDF文本拼接成带来源标注的格式。"""
    parts = []
    for filename, text in all_texts.items():
        parts.append(f"===文件: {filename}===\n{text}")
    return "\n\n".join(parts)


def _parse_json_response(response_str: str) -> dict:
    """解析AI返回的JSON，兼容markdown代码块包裹的情况。"""
    try:
        return json.loads(response_str)
    except json.JSONDecodeError:
        pass

    # 尝试去掉 ```json ... ``` 包裹
    cleaned = response_str.strip()
    if cleaned.startswith("```"):
        lines = cleaned.split("\n")
        # 去掉首行 ```json 和末行 ```
        lines = [l for l in lines if not l.strip().startswith("```")]
        cleaned = "\n".join(lines)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error("JSON解析失败，原始响应: %s", response_str[:500])
        raise ValueError(f"AI返回结果无法解析为JSON: {e}") from e


def extract_case_info(all_texts: dict[str, str]) -> dict:
    """
    接收所有PDF文本，合并后一次性发送给AI进行跨文档结构化提取。

    Args:
        all_texts: {文件名: 提取文本} 的字典

    Returns:
        完整的案件信息字典
    """
    if not DASHSCOPE_API_KEY:
        raise ValueError("未设置 DASHSCOPE_API_KEY 环境变量")

    documents_text = _build_documents_text(all_texts)
    user_prompt = USER_PROMPT_TEMPLATE.format(
        documents_text=documents_text,
        schema_json=SCHEMA_JSON_STR,
    )

    logger.info("调用AI模型提取案件信息，共 %d 份文档", len(all_texts))

    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )

    result_str = resp.choices[0].message.content
    logger.info("AI返回结果长度: %d 字符", len(result_str))

    return _parse_json_response(result_str)


def extract_bank_name(text: str) -> str:
    """
    用AI从银行财产线索文本中提取开户行名称。

    适用于各种格式，例如：
    - "开户名：XXX；开户行：XXX银行XXX支行；账号：XXX"
    - "户名：XXX，银行账号：XXX，开户银行：招商银行"
    - "XXX，XXX银行XXX支行，账号：XXX"
    """
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "你是一个信息提取助手。用户会给一段银行账户线索文本，你只需要提取其中的开户行（银行网点名称），只返回开户行名称本身，不要返回任何其他内容。如果无法识别，返回空字符串。",
            },
            {
                "role": "user",
                "content": f"请从以下文本中提取开户行名称：\n{text}",
            },
        ],
    )

    result = resp.choices[0].message.content.strip()
    logger.info("AI提取开户行: '%s' <- '%s'", result, text[:60])
    return result


def extract_alipay_account(text: str) -> str:
    """用AI从支付宝线索文本中提取支付宝账号，优先提取手机号。"""
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一个信息提取助手。用户会给一段支付宝账户线索文本（可能是OCR识别结果，文字可能有噪声），你需要提取支付宝账号。\n"
                    "优先提取手机号（1开头的11位数字），因为支付宝账号通常就是手机号。\n"
                    "如果没有手机号，再提取其他格式的账号。\n"
                    "只返回账号本身，不要返回任何其他内容。如果无法识别，返回空字符串。"
                ),
            },
            {
                "role": "user",
                "content": f"请从以下文本中提取支付宝账号（优先手机号）：\n{text}",
            },
        ],
    )

    result = resp.choices[0].message.content.strip()
    logger.info("AI提取支付宝账号: '%s' <- '%s'", result, text[:60])
    return result


def extract_tenpay_account(text: str) -> str:
    """用AI从财付通/微信线索文本中提取微信号（wxid格式）。"""
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": "你是一个信息提取助手。用户会给一段微信/财付通账户线索文本，你只需要提取其中的微信号（wxid_开头的字符串），只返回微信号本身，不要返回任何其他内容。如果无法识别，返回空字符串。",
            },
            {
                "role": "user",
                "content": f"请从以下文本中提取微信号：\n{text}",
            },
        ],
    )

    result = resp.choices[0].message.content.strip()
    logger.info("AI提取微信号: '%s' <- '%s'", result, text[:60])
    return result


def extract_property_info(text: str) -> dict[str, str]:
    """
    用AI从房产线索文本中提取不动产权证号和地址。

    返回 {"property_certificate_number": "...", "property_address": "..."}
    """
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一个信息提取助手。用户会给一段房产线索文本，你需要提取两个字段：\n"
                    "1. 不动产权证号（如：粤（2017）深圳市不动产权第0237420号）\n"
                    "2. 房产地址（如：深圳市宝安区三十三区商住楼05B栋601）\n"
                    "只返回JSON格式：{\"property_certificate_number\": \"...\", \"property_address\": \"...\"}\n"
                    "不要包含建筑面积等其他信息。如果无法识别某个字段，返回空字符串。"
                ),
            },
            {
                "role": "user",
                "content": f"请从以下文本中提取不动产权证号和房产地址：\n{text}",
            },
        ],
    )

    result_str = resp.choices[0].message.content.strip()
    logger.info("AI提取房产信息: '%s' <- '%s'", result_str, text[:60])
    return _parse_json_response(result_str)
