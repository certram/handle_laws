import argparse
import json
import logging
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

from pdf_extractor import extract_all_pdfs
from ai_extractor import extract_case_info
from yaml_generator import generate_yaml
from doc_generator import generate_docs

PROCESSED_FILE = Path(__file__).parent / ".processed.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def _find_existing_yaml(output_folder: Path) -> Path | None:
    """在输出目录中查找已有的YAML文件。"""
    yaml_files = list(output_folder.glob("*.yaml"))
    return yaml_files[0] if yaml_files else None


def _clean_docx_files(output_dir: Path):
    """只删除输出目录中的docx文件，保留YAML。"""
    if not output_dir.exists():
        return
    for f in output_dir.rglob("*.docx"):
        f.unlink()
        logger.info("已删除: %s", f.name)


def _load_processed() -> dict[str, str]:
    """读取已处理的目录名字典 {目录名: 处理日期}。兼容旧版数组格式。"""
    if PROCESSED_FILE.exists():
        with open(PROCESSED_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            # 兼容旧版：数组 → 字典，日期留空
            return {name: "" for name in data}
        return data
    return {}


def _save_processed(processed: dict[str, str]):
    """保存已处理的目录名字典。"""
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        json.dump(processed, f, ensure_ascii=False, indent=2)


def _mark_processed(case_name: str):
    """将一个案件目录名标记为已处理。"""
    processed = _load_processed()
    processed[case_name] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _save_processed(processed)


def _extract_case_number_from_dir(dir_name: str) -> str | None:
    """
    从案件目录名提取案号。

    目录名格式: （2026）粤0305民初7045号-20260323
    以 '-' 分割，取第一部分作为案号。
    如果目录名不符合格式（如 case_one），返回 None。
    """
    import re
    match = re.match(r"^(.+)-\d+$", dir_name)
    if match:
        return match.group(1)
    return None


# AI可能输出的变体字段名 → 标准字段名
_CLUE_KEY_ALIASES = {
    "bank账号": "银行账号",
    "账户": "银行账号",
    "账号": "银行账号",
    "银行卡号": "银行账号",
    "银行": "开户银行",
    "银行名称": "开户银行",
    "开户行": "开户银行",
    "不动产证号": "不动产证号",  # 已经是标准名
    "不动产权证号": "不动产证号",
    "房产证号": "不动产证号",
    "房产": "房产地址",
    "房屋地址": "房产地址",
    "微信": "微信号",
    "微信账号": "微信号",
    "支付宝": "支付宝账号",
    "支付宝号": "支付宝账号",
}


def _normalize_case_data(case_data: dict) -> dict:
    """标准化AI提取的字段名，将变体映射为schema标准名称。"""
    preservation = case_data.get("保全信息", {})
    clues = preservation.get("财产线索", [])
    for clue in clues:
        keys_to_rename = {}
        for key in list(clue.keys()):
            if key in _CLUE_KEY_ALIASES and _CLUE_KEY_ALIASES[key] != key:
                standard_key = _CLUE_KEY_ALIASES[key]
                # 只在标准字段为空时才迁移值
                if not clue.get(standard_key, ""):
                    keys_to_rename[key] = standard_key
        for old_key, new_key in keys_to_rename.items():
            clue[new_key] = clue[old_key]
            del clue[old_key]
            logger.info("字段名标准化: '%s' → '%s'", old_key, new_key)
    return case_data


def process_case(input_folder: Path, output_folder: Path, force: bool = False, civil: bool = False) -> Path:
    """
    处理单个案件文件夹的完整流程。
    如果输出目录已有YAML文件，直接复用，跳过PDF提取和AI调用。
    force=True 时强制重新走完整流程（PDF→AI→YAML→docx）。
    civil=True 时只生成外勤类协助执行通知书（跳过鹰眼和支付宝）。
    """
    input_folder = Path(input_folder)
    output_folder = Path(output_folder)

    if not input_folder.exists():
        raise FileNotFoundError(f"输入目录不存在: {input_folder}")

    logger.info("=== 开始处理案件: %s ===", input_folder)

    # 检查是否已有YAML，有则复用（除非 force）
    existing_yaml = _find_existing_yaml(output_folder)
    if existing_yaml and not force:
        logger.info("发现已有YAML文件，复用: %s", existing_yaml.name)
        with open(existing_yaml, "r", encoding="utf-8") as f:
            case_data = yaml.safe_load(f)
    else:
        # 完整流程：PDF提取 → AI提取 → 生成YAML
        all_texts = extract_all_pdfs(input_folder)
        if not all_texts:
            raise ValueError(f"目录中没有找到PDF文件: {input_folder}")

        logger.info("成功提取 %d 份PDF文本", len(all_texts))
        case_data = extract_case_info(all_texts)
        logger.info("AI提取完成")

        # 标准化字段名
        _normalize_case_data(case_data)

        # 从目录名覆盖案号（优先使用目录名，比AI提取更准确）
        dir_case_number = _extract_case_number_from_dir(input_folder.name)
        if dir_case_number:
            case_data.setdefault("案件基础信息", {})["案号"] = dir_case_number
            logger.info("从目录名获取案号: %s", dir_case_number)

        generate_yaml(case_data, output_folder)

    # 生成协助执行通知书(docx)
    doc_files = generate_docs(case_data, output_folder, civil=civil)
    logger.info("生成了 %d 份协助执行通知书", len(doc_files))

    logger.info("========== 处理完成，输出目录: %s ==========", output_folder)
    _mark_processed(input_folder.name)
    return output_folder


def process_all_cases(input_dir: Path, output_dir: Path, only_new: bool = False, force: bool = False, civil: bool = False):
    """
    扫描输入目录，自动识别单案件或多案件模式。

    - 如果 input_dir 下有子文件夹，每个子文件夹视为一个案件
    - 如果 input_dir 下直接有PDF文件，视为单个案件（兼容旧模式）
    - only_new=True 时，只处理尚未标记为已处理的案件
    - civil=True 时只生成外勤类协助执行通知书（跳过鹰眼和支付宝）
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)

    subdirs = [d for d in sorted(input_dir.iterdir()) if d.is_dir()]

    if subdirs:
        processed = _load_processed() if only_new else {}
        if only_new:
            subdirs = [d for d in subdirs if d.name not in processed]
            logger.info("未处理的案件: %d 个", len(subdirs))
            if not subdirs:
                logger.info("没有新案件需要处理")
                return

        logger.info("检测到 %d 个案件文件夹", len(subdirs))
        for case_dir in subdirs:
            case_name = case_dir.name
            case_output = output_dir / case_name
            try:
                process_case(case_dir, case_output, force=force, civil=civil)
            except Exception as e:
                logger.error("案件 %s 处理失败: %s", case_name, e)
                continue
    else:
        # 单案件目录（无子文件夹），输出到 output_dir/案件名/ 下
        case_output = output_dir / input_dir.name
        process_case(input_dir, case_output, force=force, civil=civil)
        return

    logger.info(
        "\n"
        "    ####      ###            \n"
        "  ##    ##     ##    ###    \n"
        " ##     ##     ##  ##    \n"
        " ##     ##     ## ## \n"
        " ##     ##     ## ##    \n"
        "  ##   ##      ##  ##     \n"
        "   ####       ###    ###\n"
    )


def _regenerate_selected(output_dir: Path, case_numbers: list[str], civil: bool = False):
    """
    根据案号数字列表，从 outputs/ 中正则匹配对应目录，从YAML重新生成docx。

    case_numbers 如 ["12038", "13324"]，会匹配 outputs/ 下包含 "民初12038号" 的目录。
    """
    import re

    if not output_dir.exists():
        logger.error("outputs/ 目录不存在")
        return

    subdirs = sorted([d for d in output_dir.iterdir() if d.is_dir()])
    if not subdirs:
        logger.warning("outputs/ 下没有案件目录")
        return

    for num in case_numbers:
        # 用 "民初{num}号" 精确匹配，避免误匹配日期或其他数字
        pattern = re.compile(rf"民初{re.escape(num)}号")
        matched = [d for d in subdirs if pattern.search(d.name)]

        if not matched:
            logger.warning("案号 %s 未匹配到任何目录", num)
            continue

        if len(matched) > 1:
            logger.warning("案号 %s 匹配到多个目录，跳过: %s", num, [d.name for d in matched])
            continue

        case_dir = matched[0]
        logger.info("案号 %s → %s", num, case_dir.name)
        try:
            _regenerate_from_yaml(case_dir, civil=civil)
        except Exception as e:
            logger.error("案件 %s 重新生成失败: %s", case_dir.name, e)


def _regenerate_from_yaml(output_folder: Path, civil: bool = False):
    """
    从已有YAML文件重新生成docx（不调用PDF提取和AI）。
    适用于对某个已处理案件的文书不满意，需要重新生成的场景。
    """
    output_folder = Path(output_folder)

    if not output_folder.exists():
        raise FileNotFoundError(f"输出目录不存在: {output_folder}")

    yaml_file = _find_existing_yaml(output_folder)
    if not yaml_file:
        raise FileNotFoundError(f"目录中没有找到YAML文件: {output_folder}")

    logger.info("=== 重新生成文书（复用YAML）: %s ===", yaml_file.name)

    with open(yaml_file, "r", encoding="utf-8") as f:
        case_data = yaml.safe_load(f)

    # 删除旧docx
    _clean_docx_files(output_folder)

    # 重新生成
    doc_files = generate_docs(case_data, output_folder, civil=civil)
    logger.info("生成了 %d 份协助执行通知书", len(doc_files))
    logger.info("========== 重新生成完成，输出目录: %s ==========", output_folder)
    logger.info(
        "\n"
        "   ####        ##   ##   ###\n" 
        " ##     ##     ##  ##    ### \n"
        " ##     ##     ## ##     ###\n"
        " ##     ##     ## ##     ###\n"
        " ##     ##     ##  ##    ###\n"
        " ##     ##     ##   ##   ###\n"
        "   #####       ##    ##   # \n"
    )


def main():
    """
    主入口。
    python main.py                        # 处理 original_files/ 下所有案件
    python main.py --new                  # 只处理 original_files/ 下新增的未处理案件
    python main.py /path/to/input         # 指定输入目录
    python main.py case_two               # 指定outputs子目录名，从已有YAML重新生成docx
    python main.py --clean                # 只删除docx，复用YAML，重新生成通知书
    """
    parser = argparse.ArgumentParser(description="法律案件PDF信息提取与文书生成")
    parser.add_argument("input", nargs="?", default=None, help="输入目录或outputs子目录名")
    parser.add_argument("--new", action="store_true", help="只处理新增的未处理案件")
    parser.add_argument("--force", "-f", action="store_true", help="强制重新走完整流程（PDF→AI→YAML→docx），即使已有YAML")
    parser.add_argument("--clean", "-c", action="store_true", help="清理旧docx文件后重新生成")
    parser.add_argument("--civil", action="store_true", help="民事模式：只生成外勤类协助执行通知书（跳过鹰眼和支付宝）")
    parser.add_argument("--reset", "-r", action="store_true", help="重置：清空outputs/和original_files/下所有子目录及文件")
    parser.add_argument("--regen", action="store_true", help="从 regenerate.json 读取案号列表，从YAML重新生成docx")
    args = parser.parse_args()

    project_root = Path(__file__).parent
    output_dir = project_root / "outputs"
    original_dir = project_root / "original_files"

    # 重置模式
    if args.reset:
        for d in [output_dir, original_dir]:
            if d.exists():
                for item in d.iterdir():
                    if item.is_dir():
                        shutil.rmtree(item)
                        logger.info("已删除目录: %s", item)
                    elif item.is_file():
                        item.unlink()
                        logger.info("已删除文件: %s", item)
        if PROCESSED_FILE.exists():
            PROCESSED_FILE.unlink()
            logger.info("已删除: %s", PROCESSED_FILE.name)
        logger.info("重置完成")
        return

    # regen 模式：从 regenerate.json 读取案号，批量从YAML重新生成docx
    if args.regen:
        regen_file = project_root / "regenerate.json"
        if not regen_file.exists():
            logger.error("文件不存在: %s", regen_file)
            return

        with open(regen_file, "r", encoding="utf-8") as f:
            case_numbers = json.load(f)

        if not isinstance(case_numbers, list) or not case_numbers:
            logger.error("regenerate.json 格式错误，应为非空数组，如 [12038, 13324]")
            return

        case_numbers = [str(n) for n in case_numbers]

        logger.info("读取到 %d 个案号: %s", len(case_numbers), case_numbers)
        _regenerate_selected(output_dir, case_numbers, civil=args.civil)
        return

    if args.input:
        input_path = Path(args.input)

        # 如果指定的是outputs下的子目录名（如 case_two），直接从YAML重新生成
        output_subdir = output_dir / args.input
        if output_subdir.is_dir() and not input_path.is_dir():
            logger.info("检测到outputs子目录名: %s，从YAML重新生成", args.input)
            if args.clean:
                _clean_docx_files(output_subdir)
            _regenerate_from_yaml(output_subdir, civil=args.civil)
            return

        # 否则按原逻辑：指定输入目录，走完整流程
        input_dir = input_path
    else:
        input_dir = project_root / "original_files"

    if args.clean:
        _clean_docx_files(output_dir)

    process_all_cases(input_dir, output_dir, only_new=args.new, force=args.force, civil=args.civil)


if __name__ == "__main__":
    main()
