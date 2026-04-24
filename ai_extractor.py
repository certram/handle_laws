import json
import logging

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


def extract_credit_code(all_texts: dict[str, str], company_name: str) -> str:
    """
    从所有PDF文本中精准提取某公司的统一社会信用代码（必须18位）。

    用于主提取结果校验不通过时的二次提取。
    """
    documents_text = _build_documents_text(all_texts)
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一个信息提取助手。用户会给多份法律文书文本，你需要从中找到指定公司的统一社会信用代码。\n"
                    "统一社会信用代码规则：必须是18位，由数字0-9和大写字母A-Z组成（不含I、O、Z、S、V）。\n"
                    "OCR识别可能导致数字多一位或少一位，请仔细数清楚，确保恰好18位。\n"
                    "只返回18位代码本身，不要返回任何其他内容。如果无法确认完整18位，返回空字符串。"
                ),
            },
            {
                "role": "user",
                "content": f"请从以下文档中提取「{company_name}」的统一社会信用代码（必须18位）：\n\n{documents_text}",
            },
        ],
    )

    result = resp.choices[0].message.content.strip()
    logger.info("二次提取统一社会信用代码: '%s' <- 公司: %s", result, company_name)
    return result


def extract_id_number(all_texts: dict[str, str], person_name: str) -> str:
    """
    从所有PDF文本中精准提取某人的身份证号码（必须18位）。

    用于主提取结果校验不通过时的二次提取。
    """
    documents_text = _build_documents_text(all_texts)
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一个信息提取助手。用户会给多份法律文书文本，你需要从中找到指定人员的身份证号码。\n"
                    "身份证号码规则：必须是18位，前17位为数字，最后一位为数字或字母X。\n"
                    "OCR识别可能导致数字多一位或少一位，请仔细数清楚，确保恰好18位。\n"
                    "只返回18位身份证号码本身，不要返回任何其他内容。如果无法确认完整18位，返回空字符串。"
                ),
            },
            {
                "role": "user",
                "content": f"请从以下文档中提取「{person_name}」的身份证号码（必须18位）：\n\n{documents_text}",
            },
        ],
    )

    result = resp.choices[0].message.content.strip()
    logger.info("二次提取身份证号码: '%s' <- 姓名: %s", result, person_name)
    return result


def extract_property_clues(all_texts: dict[str, str]) -> list:
    """
    从所有PDF文本中精准提取财产线索列表（主提取为空时的二次提取）。

    返回财产线索列表，每个元素包含：类型、详细内容、归属地。
    """
    documents_text = _build_documents_text(all_texts)
    resp = client.chat.completions.create(
        model=MODEL_NAME,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "你是一个信息提取助手。用户会给多份法律文书文本，你需要从中提取所有财产线索。\n"
                    "财产线索通常出现在「财产保全申请书」「财产线索表」「财产线索」等文件中。\n"
                    "每条线索包含：\n"
                    "- 类型：银行账户、房产、股权、支付宝、财付通、车辆等\n"
                    "- 详细内容：完整的线索描述（包含开户行、账号、地址等所有细节）\n"
                    "- 归属地：城市名（如 深圳、广州）\n"
                    "只返回JSON数组，不要返回任何其他内容。格式如下：\n"
                    '[{"类型": "银行账户", "详细内容": "...", "归属地": "深圳"}]\n'
                    "如果确实没有找到任何财产线索，返回空数组 []。"
                ),
            },
            {
                "role": "user",
                "content": f"请从以下文档中提取所有财产线索：\n\n{documents_text}",
            },
        ],
    )

    result_str = resp.choices[0].message.content.strip()
    logger.info("二次提取财产线索: '%s'", result_str[:200])
    try:
        clues = _parse_json_response(result_str)
        if isinstance(clues, list):
            return clues
        logger.warning("二次提取财产线索返回非数组类型: %s", type(clues))
        return []
    except Exception as e:
        logger.warning("二次提取财产线索解析失败: %s", e)
        return []
