"""文件读取小工具：列出 ZIP 中的 PDF，并读取一份 PDF 的原始数据。"""

from pathlib import Path
from zipfile import ZipFile


def list_pdf_files(zip_path):
    """返回 ZIP 中的 PDF 文件名，包括子文件夹中的 PDF。"""
    pdf_names = []
    # r 表示只读；with 会在读取结束后自动关闭压缩包。
    with ZipFile(zip_path, "r") as archive:
        # 只读取压缩包目录，不解压文件，也不打开 PDF 正文。
        for entry in archive.infolist():
            if entry.is_dir():
                continue
            # 转成小写后判断，可以同时识别 .pdf 和 .PDF。
            if entry.filename.lower().endswith(".pdf"):
                pdf_names.append(entry.filename)
    return pdf_names


def load_preview_pdf(pdf_path="", zip_path=""):
    """返回预览文件的名称和数据；单独选择的 PDF 优先。"""
    if pdf_path:
        path = Path(pdf_path)
        return path.name, path.read_bytes()
    if not zip_path:
        raise ValueError("请先选择 PDF 或 ZIP 文件。")

    with ZipFile(zip_path, "r") as archive:
        for entry in archive.infolist():
            if not entry.is_dir() and entry.filename.lower().endswith(".pdf"):
                # 只把第一份 PDF 读进内存，不把压缩包解压到磁盘。
                if entry.flag_bits & 1:
                    raise ValueError("ZIP 内的文件需要压缩密码，请先用密码解压，再选择单个 PDF。")
                source = f"{Path(zip_path).name} 内的 {entry.filename}"
                return source, archive.read(entry)
    raise ValueError("所选 ZIP 中没有找到 PDF 文件。")
