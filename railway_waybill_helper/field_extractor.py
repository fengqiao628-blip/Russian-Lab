"""按当前中俄运单版式的位置提取第3、4、23、25栏，供人工核对。"""

import re

from PySide6.QtCore import QRectF

from pdf_reader import open_pdf_document
from pdf_text_positions import PdfTextLocator


# 定位标题，也检查其在页面上的大致位置。比例坐标以页面左上角为原点。
HEADER_SPECS = {
    3: (r"(?<!\d)3\s*发货人声明", 0.536, 0.091),
    4: (r"(?<!\d)4\s*收货人", 0.089, 0.139),
    5: (r"(?<!\d)5\s*到站", 0.032, 0.217),
    8: (r"(?<!\d)8\s*车辆由何方提供", 0.536, 0.249),
    23: (r"(?<!\d)23\s*运送费用的支付", 0.032, 0.649),
    24: (r"(?<!\d)24\s*发货人添附的文件", 0.032, 0.771),
    25: (r"(?<!\d)25\s*与承运人无关的信息[^\r\n]*[\r\n]+Информация,[^\r\n]*поставку", 0.480, 0.821),
    26: (r"(?<!\d)26\s*缔结运输合同的日期", 0.032, 0.885),
}


def _join_lines(words):
    """把同一行的词从左到右排列，再把各行从上到下排列。"""
    words.sort(key=lambda item: (item[1].center().y(), item[1].left()))
    lines = []
    for text, rectangle in words:
        y = rectangle.center().y()
        # 同一行不同字体的位置会有细小差异，允许 2 个 PDF 点的偏差。
        if not lines or abs(y - lines[-1][0]) > 2:
            lines.append((y, [(text, rectangle)]))
        else:
            lines[-1][1].append((text, rectangle))
    return "\n".join(
        " ".join(text for text, rectangle in sorted(items, key=lambda item: item[1].left()))
        for y, items in lines
    )


def extract_review_fields(pdf_data, field_numbers):
    """返回启用栏的 {栏号: 原文}；仅处理当前样本版式的第 1 页。"""
    numbers = tuple(field_numbers)
    if not numbers or any(number not in (3, 4, 23, 25) for number in numbers):
        raise ValueError("请至少启用第3、4、23、25栏中的一个栏位。")

    with open_pdf_document(pdf_data) as document:
        # 这里保留原始换行，避免改变 Qt 使用的文字索引。
        locator = PdfTextLocator(document)
        raw_text = locator.text
        size = document.pagePointSize(0)
        if size.isEmpty() or not 0.68 < size.width() / size.height() < 0.73:
            raise ValueError("页面比例与当前中俄运单版式不符，请人工核对。")

        headers = {}
        for number, (pattern, expected_x, expected_y) in HEADER_SPECS.items():
            match = re.search(pattern, raw_text)
            if match is None:
                raise ValueError(f"没有找到第{number}栏的定位标题，当前版式暂不支持。")
            rectangle = locator.rectangle(match.start(), match.end())
            if (rectangle.isEmpty()
                    or abs(rectangle.left() / size.width() - expected_x) > 0.035
                    or abs(rectangle.top() / size.height() - expected_y) > 0.025):
                raise ValueError(f"第{number}栏标题的位置与当前版式不符，请人工核对。")
            headers[number] = rectangle

        # 用附近栏标题确定上下边界，避开本栏标题和相邻栏。
        right = size.width() * 0.98
        edges = {
            3: (headers[3].left()-2, headers[3].bottom()+2, right, headers[8].top()-2),
            4: (headers[4].left()-2, headers[4].bottom()+2, headers[3].left()-5, headers[5].top()-2),
            23: (headers[23].left()-2, headers[23].bottom()+2, headers[25].left()-4, headers[24].top()-2),
            25: (headers[25].left()-2, headers[25].bottom()+2, right, headers[26].top()-2),
        }
        areas = {}
        for number in numbers:
            left, top, right, bottom = edges[number]
            areas[number] = QRectF(left, top, right-left, bottom-top)
        if any(area.isEmpty() for area in areas.values()):
            raise ValueError("栏位边界无法确定，请人工核对当前 PDF 的版式。")

        selected_words = {number: [] for number in numbers}
        for match in re.finditer(r"\S+", raw_text):
            rectangle = locator.rectangle(match.start(), match.end())
            if rectangle.isEmpty():
                continue
            for number, area in areas.items():
                if area.contains(rectangle.center()):
                    selected_words[number].append((match.group(), rectangle))

        return {number: _join_lines(words) for number, words in selected_words.items()}
