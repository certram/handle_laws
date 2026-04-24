"""清空 outputs 目录和 .processed.json，用于测试前重置环境。"""

import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
OUTPUT_DIR = PROJECT_ROOT / "outputs"
PROCESSED_FILE = PROJECT_ROOT / ".processed.json"


def clear_outputs():
    """清空 outputs 目录（删除所有子目录和文件，保留 outputs 目录本身）。"""
    if not OUTPUT_DIR.exists():
        print("outputs/ 目录不存在，跳过")
        return

    count = 0
    for item in OUTPUT_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item)
            count += 1
        elif item.is_file():
            item.unlink()
            count += 1
    print(f"已清空 outputs/，删除 {count} 项")


def clear_processed():
    """清空 .processed.json（保留空 JSON 对象 {}）。"""
    with open(PROCESSED_FILE, "w", encoding="utf-8") as f:
        f.write("{}")
    print("已清空 .processed.json → {}")


if __name__ == "__main__":
    clear_outputs()
    clear_processed()
    print("重置完成")
