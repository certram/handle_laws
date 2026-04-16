import logging
from datetime import datetime
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

REQUIRED_KEYS = ["案件基础信息", "原告", "被告", "保全信息", "担保信息"]


def validate_case_data(data: dict) -> list[str]:
    """验证提取数据的完整性，返回缺失的顶级key列表。"""
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        logger.warning("以下字段缺失: %s", missing)
    return missing


def generate_output_filename(data: dict) -> str:
    """根据案号生成输出文件名。"""
    case_info = data.get("案件基础信息", {})
    case_number = case_info.get("案号", "")
    date_str = datetime.now().strftime("%Y%m%d")

    if case_number:
        # 从案号中提取数字部分作为文件名
        safe_name = "".join(c for c in case_number if c.isalnum())
        return f"{safe_name}_{date_str}.yaml"
    return f"case_{date_str}.yaml"


def generate_yaml(data: dict, output_dir: Path) -> Path:
    """
    将结构化数据写入YAML文件。

    Args:
        data: AI提取的结构化案件数据
        output_dir: 输出目录路径

    Returns:
        生成的YAML文件路径
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # 验证
    missing = validate_case_data(data)
    if missing:
        logger.warning("数据不完整，缺失字段: %s", missing)

    # 生成文件
    filename = generate_output_filename(data)
    output_path = output_dir / filename

    yaml_str = yaml.dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )

    output_path.write_text(yaml_str, encoding="utf-8")
    logger.info("YAML文件已生成: %s", output_path)

    return output_path
