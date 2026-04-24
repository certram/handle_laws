import logging
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pdfplumber
import yaml

logger = logging.getLogger(__name__)

# 加载 OCR 配置
_settings_path = Path(__file__).parent / "settings.yaml"
with open(_settings_path, "r", encoding="utf-8") as f:
    _settings = yaml.safe_load(f)

_ocr_config = _settings.get("ocr", {})
_ocr_provider = _ocr_config.get("provider", "ocrmypdf")
_ocr_force = _ocr_config.get("force", False)


def _ocr_with_zhipu(pdf_path: Path) -> str:
    """使用智谱GLM-4V进行OCR。"""
    from zhipu_ocr import ocr_pdf
    return ocr_pdf(pdf_path)


def _ocr_with_ocrmypdf(pdf_path: Path) -> str:
    """使用ocrmypdf（Tesseract）进行OCR。"""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = [
            "ocrmypdf",
            "-l", "chi_sim",
            "--rotate-pages",
            "--deskew",
            "--clean",
            str(pdf_path),
            tmp_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error("OCR处理失败: %s", result.stderr)
            return ""

        with pdfplumber.open(tmp_path) as pdf:
            ocr_pages = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    ocr_pages.append(text)
            return "\n\n".join(ocr_pages)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def extract_text_from_single_pdf(pdf_path: Path) -> str:
    """从单个PDF提取文本。force=True 时所有PDF走OCR，否则文本型PDF直接提取。"""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"{pdf_path} 不存在")

    # force 模式：所有PDF都走OCR
    if _ocr_force and _ocr_provider == "zhipu":
        logger.info("强制OCR模式: %s", pdf_path.name)
        return _ocr_with_zhipu(pdf_path)

    # 1. 尝试文本型PDF
    text_pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_pages.append(text)

    if text_pages:
        logger.info("文本型PDF，直接提取成功: %s", pdf_path.name)
        return "\n\n".join(text_pages)

    # 2. 图片型PDF，OCR兜底
    logger.info("检测到图片型PDF，使用 %s OCR: %s", _ocr_provider, pdf_path.name)

    if _ocr_provider == "zhipu":
        return _ocr_with_zhipu(pdf_path)
    else:
        return _ocr_with_ocrmypdf(pdf_path)


def extract_all_pdfs(folder_path: Path, max_workers: int = 2) -> dict[str, str]:
    """
    遍历文件夹中所有PDF，返回 {文件名: 提取文本} 的字典。
    多个PDF并行提取，文本型PDF不需要并发（很快），OCR型PDF并行可节省时间。
    """
    folder_path = Path(folder_path)
    if not folder_path.exists():
        raise FileNotFoundError(f"文件夹不存在: {folder_path}")

    results = {}
    pdf_files = sorted(folder_path.glob("*.pdf"))

    if not pdf_files:
        logger.warning("文件夹中没有PDF文件: %s", folder_path)
        return results

    total = len(pdf_files)
    logger.info("共 %d 个PDF文件，并行提取", total)

    if max_workers <= 1 or total <= 1:
        # 单线程：直接顺序处理
        for i, pdf_file in enumerate(pdf_files, 1):
            logger.info("正在处理 PDF %d/%d: %s", i, total, pdf_file.name)
            text = extract_text_from_single_pdf(pdf_file)
            results[pdf_file.name] = text
    else:
        # 多线程并行提取
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_name = {
                executor.submit(extract_text_from_single_pdf, pdf_file): pdf_file.name
                for pdf_file in pdf_files
            }
            for future in as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    text = future.result()
                    results[name] = text
                    logger.info("PDF提取完成: %s", name)
                except Exception as e:
                    logger.error("PDF提取失败 %s: %s", name, e)
                    results[name] = ""

    return results
