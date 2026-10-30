"""第七步主窗口：支持特殊字符定位修复的单份和 ZIP 批量审核。"""

from pathlib import Path
from zipfile import BadZipFile

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from batch_review import BatchReviewWorker, format_batch_report
from file_reader import list_pdf_files, load_preview_pdf
from field_extractor import extract_review_fields
from pdf_reader import read_first_page
from reviewer import build_review_report, split_requirements


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("铁路运单草单审核助手")
        self.resize(980, 780)
        self.setMinimumSize(760, 700)

        # 用字典保存各栏的复选框和输入框，便于后面读取内容。
        self.review_fields = {}
        self._batch_worker = None
        self._batch_results = []
        self._last_batch_summary = None
        self._cancel_requested = False
        self._close_after_batch = False
        self._viewing_batch_item = False

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 16, 20, 16)
        main_layout.setSpacing(12)

        title = QLabel("铁路运单草单审核助手")
        title_font = title.font()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title.setFont(title_font)
        main_layout.addWidget(title)
        main_layout.addWidget(QLabel("第七步：ZIP 批量审核（文字定位修复）"))

        files_group = QGroupBox("待审核文件")
        files_layout = QGridLayout(files_group)
        self.pdf_button = QPushButton("选择 PDF")
        self.zip_button = QPushButton("选择 ZIP")
        self.list_button = QPushButton("查看 ZIP 文件清单")
        self.pdf_path = QLineEdit()
        self.zip_path = QLineEdit()
        self.pdf_path.setPlaceholderText("尚未选择 PDF 文件")
        self.zip_path.setPlaceholderText("尚未选择 ZIP 文件")
        # 路径由文件选择框填写；仍可选中、复制和左右滚动查看。
        self.pdf_path.setReadOnly(True)
        self.zip_path.setReadOnly(True)
        files_layout.addWidget(self.pdf_button, 0, 0)
        files_layout.addWidget(self.pdf_path, 0, 1, 1, 2)
        files_layout.addWidget(self.zip_button, 1, 0)
        files_layout.addWidget(self.zip_path, 1, 1)
        files_layout.addWidget(self.list_button, 1, 2)
        files_layout.setColumnStretch(1, 1)
        main_layout.addWidget(files_group)

        rule_label = QLabel("审核规则：每行填写一段本栏必须包含的原文或编号；统一大小写，将换行和连续空白视为一个空格。")
        rule_label.setWordWrap(True)
        main_layout.addWidget(rule_label)

        # 同一个函数创建四个相似区域，避免复制四份界面代码。
        fields_layout = QGridLayout()
        for index, number in enumerate((3, 4, 23, 25)):
            group = self.create_review_group(number, enabled=(number != 25))
            # 整除得到行号，取余得到列号，排列为两行两列。
            fields_layout.addWidget(group, index // 2, index % 2)
        fields_layout.setColumnStretch(0, 1)
        fields_layout.setColumnStretch(1, 1)
        main_layout.addLayout(fields_layout, stretch=2)

        self.start_button = QPushButton("开始审核（单份）")
        self.start_button.setToolTip("只检查所选单个 PDF，或 ZIP 内第一份 PDF 的第 1 页。")
        self.start_button.setMinimumHeight(36)
        self.batch_button = QPushButton("开始 ZIP 批量审核")
        self.batch_button.setMinimumHeight(36)
        self.batch_button.setToolTip("使用 ZIP 路径，逐份检查其中所有 PDF 的第 1 页。")
        self.preview_button = QPushButton("预览 PDF 第一页文字")
        self.preview_button.setMinimumHeight(36)
        self.preview_button.setToolTip(
            "优先读取单独选择的 PDF；否则预览 ZIP 中第一份 PDF 的第一页。"
        )
        self.fields_button = QPushButton("预览各栏提取内容")
        self.fields_button.setMinimumHeight(36)
        self.fields_button.setToolTip("提取已启用的栏位；仅预览单个 PDF 或 ZIP 第一份 PDF 的第 1 页。")
        buttons_layout = QHBoxLayout()
        buttons_layout.addWidget(self.start_button)
        buttons_layout.addWidget(self.batch_button)
        buttons_layout.addWidget(self.preview_button)
        buttons_layout.addWidget(self.fields_button)
        main_layout.addLayout(buttons_layout)

        progress_layout = QHBoxLayout()
        self.batch_progress = QProgressBar()
        self.batch_progress.setRange(0, 1)
        self.batch_progress.setValue(0)
        self.batch_progress.setFormat("%v / %m")
        self.batch_progress.hide()
        self.cancel_batch_button = QPushButton("取消批量审核")
        self.cancel_batch_button.setEnabled(False)
        self.cancel_batch_button.hide()
        progress_layout.addWidget(self.batch_progress, stretch=1)
        progress_layout.addWidget(self.cancel_batch_button)
        main_layout.addLayout(progress_layout)

        results_group = QGroupBox("审核结果")
        results_layout = QVBoxLayout(results_group)
        self.batch_status_label = QLabel("批量任务尚未开始。")
        self.batch_status_label.setWordWrap(True)
        results_layout.addWidget(self.batch_status_label)
        self.result_tabs = QTabWidget()
        self.results_text = QPlainTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setPlaceholderText(
            "选择文件，在启用栏中逐行填写必含文字，再点击“开始审核（单份）”。\n"
            "“开始 ZIP 批量审核”会逐份检查 ZIP 中所有 PDF 的第 1 页。"
        )
        self.result_tabs.addTab(self.results_text, "审核详情")
        batch_page = QWidget()
        batch_page_layout = QVBoxLayout(batch_page)
        batch_hint_layout = QHBoxLayout()
        batch_hint_layout.addWidget(QLabel("双击文件行查看详细结果。"), stretch=1)
        self.batch_summary_button = QPushButton("查看批次汇总")
        self.batch_summary_button.setEnabled(False)
        batch_hint_layout.addWidget(self.batch_summary_button)
        batch_page_layout.addLayout(batch_hint_layout)
        self.batch_table = QTableWidget(0, 4)
        self.batch_table.setHorizontalHeaderLabels(["序号", "PDF 文件名", "结果", "说明"])
        self.batch_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.batch_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.batch_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.batch_table.verticalHeader().hide()
        header = self.batch_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        batch_page_layout.addWidget(self.batch_table)
        self.result_tabs.addTab(batch_page, "批量清单")
        results_layout.addWidget(self.result_tabs)
        main_layout.addWidget(results_group, stretch=2)

        # connect 后面写函数名，不加括号：等按钮被点击时再调用。
        self.pdf_button.clicked.connect(self.select_pdf)
        self.zip_button.clicked.connect(self.select_zip)
        self.list_button.clicked.connect(self.show_file_list)
        self.start_button.clicked.connect(self.start_review)
        self.batch_button.clicked.connect(self.start_batch_review)
        self.cancel_batch_button.clicked.connect(self.cancel_batch_review)
        self.batch_summary_button.clicked.connect(self.show_batch_summary)
        self.batch_table.cellDoubleClicked.connect(self.show_batch_item)
        self.preview_button.clicked.connect(self.preview_pdf_text)
        self.fields_button.clicked.connect(self.preview_field_contents)

    def create_review_group(self, number, enabled):
        """创建一个审核栏，并设置它的默认启用状态。"""
        group = QGroupBox(f"第{number}栏审核要求")
        layout = QVBoxLayout(group)
        checkbox = QCheckBox("启用本栏审核（取消勾选即停用）")
        checkbox.setChecked(enabled)
        text_edit = QPlainTextEdit()
        text_edit.setPlaceholderText(f"每行填写一段第{number}栏必须包含的原文或编号……")
        text_edit.setEnabled(enabled)

        # 勾选变化时自动启用或禁用输入框；停用不会清空已经填写的文字。
        checkbox.toggled.connect(text_edit.setEnabled)
        layout.addWidget(checkbox)
        layout.addWidget(text_edit)
        self.review_fields[number] = {"checkbox": checkbox, "text_edit": text_edit}
        return group

    def select_pdf(self):
        # 返回值依次是文件路径、所选过滤器；下划线表示暂时不用的值。
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 PDF 文件", "", "PDF 文件 (*.pdf)"
        )
        # 取消选择时路径为空，此时保留上一次选择。
        if file_path:
            self.pdf_path.setText(file_path)
            self.pdf_path.setToolTip(file_path)

    def select_zip(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择 ZIP 文件", "", "ZIP 压缩文件 (*.zip)"
        )
        if file_path:
            self.zip_path.setText(file_path)
            self.zip_path.setToolTip(file_path)

    def show_file_list(self):
        """读取 ZIP 中的 PDF 清单，并显示当前填写的审核要求。"""
        self.result_tabs.setCurrentIndex(0)
        pdf_path = self.pdf_path.text()
        zip_path = self.zip_path.text()
        if not pdf_path and not zip_path:
            self.results_text.setPlainText("请先选择 PDF 或 ZIP 文件，再查看文件清单。")
            return

        lines = [
            "【PDF 文件清单】点击“开始审核（单份）”可检查第一份 PDF 的必含文字。",
            f"PDF：{pdf_path or '未选择'}",
            f"ZIP：{zip_path or '未选择'}",
            "",
        ]
        if zip_path:
            try:
                # 把读取文件的工作交给小工具函数，窗口负责展示结果。
                pdf_names = list_pdf_files(zip_path)
            except BadZipFile:
                lines.append("读取 ZIP 失败：文件不是有效的 ZIP，或压缩包目录已损坏。")
                lines.append("请重新选择一个能正常打开的 ZIP 压缩包。")
                self.results_text.setPlainText("\n".join(lines))
                return
            except OSError as error:
                lines.append("读取 ZIP 失败：无法访问该文件，请检查文件位置和读取权限。")
                lines.append(f"详细原因：{error}")
                self.results_text.setPlainText("\n".join(lines))
                return
            except (UnicodeError, NotImplementedError) as error:
                lines.append("读取 ZIP 失败：压缩包的文件名编码或格式暂不支持。")
                lines.append(f"详细原因：{error}")
                self.results_text.setPlainText("\n".join(lines))
                return

            lines.append(f"ZIP 中找到 {len(pdf_names)} 个 PDF：")
            if pdf_names:
                # 从 1 开始编号，文件名包含其在 ZIP 内的子文件夹路径。
                for index, name in enumerate(pdf_names, start=1):
                    lines.append(f"{index}. {name}")
            else:
                lines.append("没有找到以 .pdf 结尾的文件，请确认所选压缩包。")
        else:
            lines.append("已选择单个 PDF；填写要求后点击“开始审核（单份）”执行检查。")

        lines.extend(["", "【审核要求预览】"])
        for number, controls in self.review_fields.items():
            lines.append("")
            if controls["checkbox"].isChecked():
                requirement = controls["text_edit"].toPlainText().strip()
                lines.append(f"第{number}栏（启用）：")
                lines.append(requirement or "（尚未填写审核要求）")
            else:
                lines.append(f"第{number}栏：已停用")
        self.results_text.setPlainText("\n".join(lines))

    def start_review(self):
        """对一份 PDF 的启用栏执行必含文字检查。"""
        self.result_tabs.setCurrentIndex(0)
        pdf_path = self.pdf_path.text()
        zip_path = self.zip_path.text()
        if not pdf_path and not zip_path:
            self.results_text.setPlainText("未开始审核：请先选择 PDF 或 ZIP 文件。")
            return
        try:
            requirements = self.collect_requirements()
        except ValueError as error:
            self.results_text.setPlainText(f"未开始审核：{error}")
            return
        # 点击时记录要求，读取、定位、比对，最后把报告显示出来。
        self.start_button.setEnabled(False)
        self.start_button.setText("正在审核……")
        self.start_button.repaint()
        self.results_text.setPlainText("正在读取文件、提取栏位并比对，请稍候……")
        self.results_text.repaint()
        try:
            source, data = load_preview_pdf(pdf_path, zip_path)
            if pdf_path:
                scope = "单个 PDF 的第 1 页。"
            else:
                count = len(list_pdf_files(zip_path))
                scope = f"ZIP 共 {count} 份 PDF；本次只检查第一份的第 1 页，其余文件尚未审核。"
            fields = extract_review_fields(data, requirements.keys())
            report = build_review_report(source, scope, fields, requirements)
            self.results_text.setPlainText(report)
        except BadZipFile:
            self.results_text.setPlainText("未完成审核：所选文件不是有效 ZIP，或压缩包目录已损坏。")
        except (OSError, ValueError, RuntimeError) as error:
            self.results_text.setPlainText(f"未完成审核：读取文件或提取栏位失败。\n{error}")
        finally:
            self.start_button.setText("开始审核（单份）")
            self.start_button.setEnabled(True)

    def collect_requirements(self):
        """单份和批量共用的输入校验，返回启用栏的要求。"""
        requirements = {
            number: controls["text_edit"].toPlainText()
            for number, controls in self.review_fields.items()
            if controls["checkbox"].isChecked()
        }
        if not requirements:
            raise ValueError("请至少启用一个审核栏。")
        missing = [f"第{number}栏" for number, text in requirements.items() if not split_requirements(text)]
        if missing:
            raise ValueError(
                "以下启用栏尚未填写要求：" + "、".join(missing)
                + "。\n请逐行填写对应栏必须包含的原文或编号；暂无要求的栏可以取消勾选。"
            )
        return requirements

    def start_batch_review(self):
        """启动后台 ZIP 任务；批量模式始终使用 ZIP 路径。"""
        if self._batch_worker is not None:
            return
        self.result_tabs.setCurrentIndex(0)
        if not self.zip_path.text():
            self.results_text.setPlainText("未开始批量审核：请先选择 ZIP 文件。")
            return
        try:
            requirements = self.collect_requirements()
        except ValueError as error:
            self.results_text.setPlainText(f"未开始批量审核：{error}")
            return
        self._batch_results = []
        self._last_batch_summary = None
        self._cancel_requested = False
        self._viewing_batch_item = False
        self.batch_table.setRowCount(0)
        self.batch_summary_button.setEnabled(False)
        self.batch_status_label.setText("正在读取 ZIP 目录……")
        self.results_text.setPlainText("批量处理中；结果会逐项出现在“批量清单”中。")
        self.batch_progress.show()
        self.batch_progress.setRange(0, 0)
        self.cancel_batch_button.show()
        self.set_batch_running(True)
        self.result_tabs.setCurrentIndex(1)
        self._batch_worker = BatchReviewWorker(self.zip_path.text(), requirements, self)
        self._batch_worker.progress.connect(self.on_batch_progress)
        self._batch_worker.item_ready.connect(self.on_batch_item)
        self._batch_worker.completed.connect(self.on_batch_completed)
        self._batch_worker.finished.connect(self.on_batch_finished)
        self._batch_worker.start()

    def set_batch_running(self, running):
        """任务期间固定输入和文件，防止中途更换规则或重复启动。"""
        for button in (self.pdf_button, self.zip_button, self.list_button, self.start_button,
                       self.batch_button, self.preview_button, self.fields_button):
            button.setEnabled(not running)
        for controls in self.review_fields.values():
            controls["checkbox"].setEnabled(not running)
            controls["text_edit"].setEnabled(not running and controls["checkbox"].isChecked())
        self.cancel_batch_button.setEnabled(running)

    def cancel_batch_review(self):
        if self._batch_worker is not None:
            self._cancel_requested = True
            self._batch_worker.requestInterruption()
            self.cancel_batch_button.setEnabled(False)
            self.batch_status_label.setText("正在停止：当前文件处理结束后停止，已完成结果会保留。")

    @Slot(int, int, str)
    def on_batch_progress(self, done, total, message):
        self.batch_progress.setRange(0, max(1, total))
        self.batch_progress.setValue(done)
        if self._cancel_requested:
            self.batch_status_label.setText(f"正在停止：已处理 {done}/{total}，当前文件结束后停止。")
        else:
            self.batch_status_label.setText(message)

    @Slot(object)
    def on_batch_item(self, result):
        self._batch_results.append(result)
        row = self.batch_table.rowCount()
        self.batch_table.insertRow(row)
        values = (str(result["index"]), result["name"], result["status"], result["note"])
        for column, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setToolTip(value)
            self.batch_table.setItem(row, column, item)

    @Slot(object)
    def on_batch_completed(self, summary):
        self._last_batch_summary = summary
        state = "未完成" if summary["error"] else "已取消" if summary["cancelled"] else "已完成"
        self.batch_status_label.setText(
            f"{Path(summary['zip_path']).name}：{state} {summary['processed']}/{summary['total']}；"
            f"匹配 {summary['matched']}，需复核 {summary['needs_review']}，失败 {summary['failed']}，"
            f"未处理 {summary['remaining']}。"
        )
        self.batch_progress.setRange(0, max(1, summary["total"]))
        self.batch_progress.setValue(summary["processed"])
        self.batch_summary_button.setEnabled(True)
        if not self._viewing_batch_item:
            self.results_text.setPlainText(format_batch_report(summary))
        if summary["error"]:
            self.show_batch_summary()

    @Slot()
    def on_batch_finished(self):
        worker = self._batch_worker
        if worker is not None:
            worker.wait()
            self._batch_worker = None
            worker.deleteLater()
        self.set_batch_running(False)
        if self._close_after_batch:
            self.close()

    def show_batch_item(self, row, column):
        if 0 <= row < len(self._batch_results):
            self._viewing_batch_item = True
            self.results_text.setPlainText(self._batch_results[row]["report"])
            self.result_tabs.setCurrentIndex(0)

    def show_batch_summary(self):
        if self._last_batch_summary is not None:
            self._viewing_batch_item = False
            self.results_text.setPlainText(format_batch_report(self._last_batch_summary))
            self.result_tabs.setCurrentIndex(0)

    def closeEvent(self, event):
        # 不强行终止线程。等待当前文件完成，避免关闭窗口时线程仍在运行。
        if self._batch_worker is not None and self._batch_worker.isRunning():
            self._close_after_batch = True
            self.cancel_batch_review()
            event.ignore()
        else:
            super().closeEvent(event)

    def preview_pdf_text(self):
        """读取一份 PDF 并打开文字预览，不改变各栏审核要求。"""
        self.result_tabs.setCurrentIndex(0)
        try:
            source, data = load_preview_pdf(self.pdf_path.text(), self.zip_path.text())
            page_count, text = read_first_page(data)
        except BadZipFile:
            self.results_text.setPlainText("PDF 文字预览失败：所选文件不是有效 ZIP，或压缩包目录已损坏。")
            return
        except (OSError, ValueError, RuntimeError) as error:
            self.results_text.setPlainText(f"PDF 文字预览失败：\n{error}")
            return

        # 使用独立预览窗口，文字更容易阅读，也方便选中复制。
        dialog = QDialog(self)
        dialog.setWindowTitle("PDF 第一页文字预览")
        dialog.resize(820, 620)
        layout = QVBoxLayout(dialog)
        source_label = QLabel(f"文件：{source}")
        source_label.setWordWrap(True)
        layout.addWidget(source_label)
        layout.addWidget(QLabel(f"共 {page_count} 页；当前预览第 1 页；提取到 {len(text)} 个字符。"))
        text_edit = QPlainTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setPlainText(text or (
            "这一页没有提取到可读文字。可能是扫描图片、空白页或文字编码不受支持。\n"
            "当前步骤尚未接入 OCR。"
        ))
        layout.addWidget(text_edit)
        layout.addWidget(QLabel("此窗口显示整页原始文字；各栏提取和要求比对可回到主窗口操作。"))
        close_button = QPushButton("关闭预览")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        # exec() 等待这个预览窗口被关闭，再回到主窗口。
        dialog.exec()

    def preview_field_contents(self):
        """预览启用栏的 PDF 原文；主窗口输入框继续用于填写期望要求。"""
        self.result_tabs.setCurrentIndex(0)
        enabled = [
            number for number, controls in self.review_fields.items()
            if controls["checkbox"].isChecked()
        ]
        self.fields_button.setEnabled(False)
        self.fields_button.setText("正在提取……")
        self.fields_button.repaint()
        try:
            source, data = load_preview_pdf(self.pdf_path.text(), self.zip_path.text())
            fields = extract_review_fields(data, enabled)
        except BadZipFile:
            self.results_text.setPlainText("栏位提取失败：所选文件不是有效 ZIP，或压缩包目录已损坏。")
            return
        except (OSError, ValueError, RuntimeError) as error:
            self.results_text.setPlainText(f"栏位提取失败：\n{error}")
            return
        finally:
            self.fields_button.setText("预览各栏提取内容")
            self.fields_button.setEnabled(True)

        dialog = QDialog(self)
        dialog.setWindowTitle("运单各栏内容预览")
        dialog.resize(980, 700)
        layout = QVBoxLayout(dialog)
        source_label = QLabel(f"文件：{source}；当前预览第 1 页。")
        source_label.setWordWrap(True)
        layout.addWidget(source_label)
        layout.addWidget(QLabel("当前支持样本的中俄运单版式，请对照原 PDF 核对提取范围。"))
        grid = QGridLayout()
        for index, number in enumerate((3, 4, 23, 25)):
            active = number in fields
            group = QGroupBox(f"第{number}栏 PDF 原文（{'启用' if active else '停用'}）")
            group_layout = QVBoxLayout(group)
            editor = QPlainTextEdit()
            editor.setObjectName(f"extracted_field_{number}")
            editor.setReadOnly(True)
            if active:
                editor.setPlainText(fields[number] or "本栏范围内没有提取到文字，请对照原文件检查。")
            else:
                editor.setPlainText("本栏已停用，本次未提取。")
                editor.setEnabled(False)
            group_layout.addWidget(editor)
            grid.addWidget(group, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid, stretch=1)
        layout.addWidget(QLabel("此窗口供核对提取范围；执行比对请关闭预览后点击“开始审核（单份）”。"))
        close_button = QPushButton("关闭预览")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button)
        dialog.exec()
