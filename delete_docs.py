"""
删除 outputs/ 下匹配关键词的协助执行通知书。

两种使用方式：
1. 读取 settings.yaml 的 delete 配置：
   python3 delete_docs.py

2. 命令行直接指定关键词（覆盖配置文件）：
   python3 delete_docs.py 支付宝 财付通 银行
"""

import argparse
import logging
from pathlib import Path

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent
SETTINGS_PATH = PROJECT_ROOT / "settings.yaml"
OUTPUTS_DIR = PROJECT_ROOT / "outputs"


def _load_delete_keywords() -> list[str]:
    """从 settings.yaml 读取 delete 配置。"""
    with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)
    return settings.get("delete", [])


def _delete_matching_docs(keywords: list[str], dry_run: bool = False) -> int:
    """
    扫描 outputs/ 下所有案件目录，删除文件名匹配关键词的协助执行通知书。

    只删除"协助执行通知书"开头的文件，不会删除裁定书和保全卷。

    Args:
        keywords: 要匹配的关键词列表
        dry_run: 只预览不实际删除

    Returns:
        删除/匹配的文件数量
    """
    if not keywords:
        logger.info("没有配置删除关键词，退出")
        return 0

    if not OUTPUTS_DIR.exists():
        logger.info("outputs/ 目录不存在，退出")
        return 0

    logger.info("删除关键词: %s", "、".join(keywords))

    count = 0
    for case_dir in sorted(OUTPUTS_DIR.iterdir()):
        if not case_dir.is_dir():
            continue

        for docx in sorted(case_dir.glob("协助执行通知书*.docx")):
            filename = docx.name
            if any(kw in filename for kw in keywords):
                count += 1
                if dry_run:
                    logger.info("[预览] 将删除: %s/%s", case_dir.name, filename)
                else:
                    docx.unlink()
                    logger.info("已删除: %s/%s", case_dir.name, filename)

    if count == 0:
        logger.info("没有匹配的文件")

    return count


def main():
    parser = argparse.ArgumentParser(description="删除匹配关键词的协助执行通知书")
    parser.add_argument(
        "keywords",
        nargs="*",
        help="要删除的关键词（如：支付宝 财付通 银行），不指定则读取 settings.yaml 的 delete 配置",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只预览要删除的文件，不实际删除",
    )
    args = parser.parse_args()

    keywords = args.keywords or _load_delete_keywords()
    _delete_matching_docs(keywords, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
