"""PDF 小工具：管理文档的打开、关闭，并读取第一页文字。"""

from contextlib import contextmanager
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtPdf import QPdfDocument


@contextmanager
def open_pdf_document(pdf_data):
    """用 with 打开 PDF；退出 with 时自动关闭文档和缓冲区。"""
    # QBuffer 把内存里的文件数据交给 Qt，兼容 ZIP 内的 PDF。
    buffer = QBuffer()
    buffer.setData(pdf_data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    document = QPdfDocument(None)
    try:
        document.load(buffer)
        if document.status() != QPdfDocument.Status.Ready:
            error = document.error()
            if error == QPdfDocument.Error.IncorrectPassword:
                raise ValueError("这份 PDF 需要打开密码，当前步骤尚未提供密码输入功能。")
            if error == QPdfDocument.Error.UnsupportedSecurityScheme:
                raise ValueError("当前 PDF 组件不支持这份文件的加密方式。")
            raise ValueError(f"无法读取 PDF，文件可能损坏或格式不受支持。错误：{error.name}")

        page_count = document.pageCount()
        if page_count == 0:
            raise ValueError("这份 PDF 没有可读取的页面。")
        yield document
    finally:
        # 即使读取时出错，也关闭文档和缓冲区。
        document.close()
        buffer.close()


def read_first_page(pdf_data):
    """返回（总页数，第一页文字）；在已启动的 Qt 应用中调用。"""
    with open_pdf_document(pdf_data) as document:
        # 页码从 0 开始，0 对应第 1 页；同时统一 Windows 换行。
        text = document.getAllText(0).text().replace("\r\n", "\n").replace("\r", "\n").strip()
        return document.pageCount(), text
