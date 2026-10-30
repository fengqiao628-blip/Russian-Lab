"""把显示文字的下标映射到 PDF 内部字符位置，处理不可见字符造成的偏差。"""


class PdfTextLocator:
    def __init__(self, document, page=0):
        self.document = document
        self.page = page
        selection = document.getAllText(page)
        self.text = selection.text()
        # endIndex 是 PDF 内部字符边界，不一定等于 len(text)。
        self.native_count = selection.endIndex()
        self._prefixes = {0: "", self.native_count: self.text}
        self._mapped_indices = {0: 0, len(self.text): self.native_count}
        self._offsets = [(0, 0)]

    def _prefix(self, native_end):
        if native_end not in self._prefixes:
            self._prefixes[native_end] = self.document.getSelectionAtIndex(
                self.page, 0, native_end
            ).text()
        return self._prefixes[native_end]

    def _native_index(self, text_index):
        """查找文字前缀对应的内部边界，再核对整个前缀。"""
        if text_index in self._mapped_indices:
            return self._mapped_indices[text_index]
        left, right = 0, self.native_count
        # 二分查找：每次把候选范围缩小一半，不逐字遍历整份 PDF。
        while left < right:
            middle = (left + right) // 2
            if len(self._prefix(middle)) < text_index:
                left = middle + 1
            else:
                right = middle
        if self._prefix(left) != self.text[:text_index]:
            raise ValueError("这份 PDF 的文字前缀与内部位置无法可靠对应，请人工核对。")
        self._mapped_indices[text_index] = left
        return left

    def rectangle(self, start, end):
        """取得指定文字的坐标；校正前后都必须与目标文字完全一致。"""
        expected = self.text[start:end]
        offset = next((shift for boundary, shift in reversed(self._offsets) if boundary <= start), 0)
        native_start, native_end = start + offset, end + offset
        selection = self.document.getSelectionAtIndex(
            self.page, native_start, native_end - native_start
        )
        if selection.text() != expected:
            # 只有发现不一致时才做映射，普通文件继续走快速路径。
            native_start = self._native_index(start)
            native_end = self._native_index(end)
            selection = self.document.getSelectionAtIndex(
                self.page, native_start, native_end - native_start
            )
            if selection.text() != expected:
                raise ValueError("校正后文字与坐标仍无法可靠对应，请人工核对。")
            self._offsets.append((end, native_end - end))
            self._offsets.sort()

        rectangle = selection.boundingRectangle()
        if native_end - native_start != len(expected):
            # Qt 的范围矩形可能按可见文字数截断，补上真实末字符的矩形。
            tail = self.document.getSelectionAtIndex(self.page, native_end - 1, 1).boundingRectangle()
            if not tail.isEmpty():
                rectangle = rectangle.united(tail)
        if rectangle.isEmpty() and (native_start != start or native_end != end):
            # 某些短词单独查询时没有矩形；只加入相邻空白来取得位置。
            # 返回的业务文字仍是原来的词，不加入上下文字符。
            spans = []
            before = start > 0 and self.text[start - 1].isspace()
            after = end < len(self.text) and self.text[end].isspace()
            if after:
                spans.append((start, end + 1))
            if before and after:
                spans.append((start - 1, end + 1))
            if before:
                spans.append((start - 1, end))
            for context_start, context_end in spans:
                left = self._native_index(context_start)
                right = self._native_index(context_end)
                context = self.document.getSelectionAtIndex(self.page, left, right - left)
                if context.text() != self.text[context_start:context_end]:
                    continue
                if not context.boundingRectangle().isEmpty():
                    rectangle = context.boundingRectangle()
                    break
            if rectangle.isEmpty():
                raise ValueError("校正后的短词仍无法可靠确定位置，请人工核对。")
        return rectangle
