"""ZIP 批量任务：在后台线程逐份检查，使用信号把结果交给窗口。"""

from pathlib import Path
from zipfile import ZipFile

from PySide6.QtCore import QThread, Signal

from field_extractor import extract_review_fields
from reviewer import build_review_report, compare_field, split_requirements


class BatchReviewWorker(QThread):
    # 后台线程不直接操作窗口，只发送普通数据。
    progress = Signal(int, int, str)
    item_ready = Signal(object)
    completed = Signal(object)

    def __init__(self, zip_path, requirements, parent=None):
        super().__init__(parent)
        self.zip_path = str(zip_path)
        # 保存启动时的要求，之后修改输入框不影响本次任务。
        self.requirements = dict(requirements)

    def run(self):
        results = []
        total = 0
        error_message = ""
        try:
            if not self.requirements or any(not split_requirements(text) for text in self.requirements.values()):
                raise ValueError("请为每个启用栏填写至少一条必含文字。")
            with ZipFile(self.zip_path, "r") as archive:
                entries = [
                    entry for entry in archive.infolist()
                    if not entry.is_dir() and entry.filename.lower().endswith(".pdf")
                ]
                total = len(entries)
                self.progress.emit(0, total, f"ZIP 中找到 {total} 份 PDF。")
                if not entries:
                    raise ValueError("所选 ZIP 中没有找到 PDF 文件。")

                for index, entry in enumerate(entries, start=1):
                    # 协作取消：当前文件完成后，开始下一份前检查是否应停止。
                    if self.isInterruptionRequested():
                        break
                    self.progress.emit(len(results), total, f"正在处理 {index}/{total}：{entry.filename}")
                    try:
                        if entry.flag_bits & 1:
                            raise ValueError("ZIP 内的这个文件需要压缩密码，当前不支持输入 ZIP 密码。")
                        # 按 ZipInfo 读取，压缩包中即使存在同名条目也不会读错。
                        data = archive.read(entry)
                        fields = extract_review_fields(data, self.requirements.keys())
                        checks = {
                            number: compare_field(fields.get(number, ""), requirement)
                            for number, requirement in self.requirements.items()
                        }
                        pending = [number for number, check in checks.items() if check["status"] != "全部匹配"]
                        status = "需复核" if pending else "全部匹配"
                        note = "、".join(f"第{number}栏{checks[number]['status']}" for number in pending)
                        if not note:
                            note = f"{len(checks)} 个启用栏全部匹配"
                        source = f"{Path(self.zip_path).name} 内的 {entry.filename}"
                        report = build_review_report(
                            source, f"ZIP 批量任务，第 {index}/{total} 份 PDF 的第 1 页。",
                            fields, self.requirements,
                        )
                    except Exception as error:
                        # 一份失败单独记录，继续下一份；不把读取失败当作未匹配。
                        status = "读取或提取失败"
                        note = f"{type(error).__name__}: {error}"
                        report = (
                            f"【本文件未完成检查】\n文件：{entry.filename}\n原因：{note}\n"
                            "没有生成本文件的有效比对结论，请对照原文件检查。"
                        )
                    result = {"index": index, "name": entry.filename, "status": status, "note": note, "report": report}
                    results.append(result)
                    self.item_ready.emit(result)
                    self.progress.emit(len(results), total, f"已处理 {len(results)}/{total}：{entry.filename}")
        except Exception as error:
            error_message = f"{type(error).__name__}: {error}"

        processed = len(results)
        summary = {
            "zip_path": self.zip_path,
            "requirements": dict(self.requirements),
            "total": total,
            "processed": processed,
            "remaining": max(0, total - processed),
            "matched": sum(item["status"] == "全部匹配" for item in results),
            "needs_review": sum(item["status"] == "需复核" for item in results),
            "failed": sum(item["status"] == "读取或提取失败" for item in results),
            "cancelled": self.isInterruptionRequested() and processed < total,
            "error": error_message,
            "results": results,
        }
        self.completed.emit(summary)


def format_batch_report(summary):
    """生成批次汇总，明确区分完成、取消、失败和未处理文件。"""
    if summary["error"]:
        state = "未完成"
    elif summary["cancelled"]:
        state = "已取消"
    else:
        state = "已完成"
    lines = [
        f"【ZIP 批量检查：{state}】",
        f"ZIP：{summary['zip_path']}",
        "范围：压缩包中的 PDF，每份仅检查第 1 页；使用启动时的同一套要求。",
        f"文件总数：{summary['total']}；已处理：{summary['processed']}；未处理：{summary['remaining']}。",
        f"规则全部匹配：{summary['matched']}；需复核：{summary['needs_review']}；读取或提取失败：{summary['failed']}。",
    ]
    if summary["error"]:
        lines.append(f"任务错误：{summary['error']}")
    elif summary["cancelled"]:
        lines.append("任务已取消，未处理文件没有审核结论。")
    elif summary["needs_review"] or summary["failed"]:
        lines.append("请查看需复核及读取失败的文件，双击清单行可打开详情。")
    else:
        lines.append("本批次 PDF 第 1 页的当前必含文字规则全部匹配。")
    lines.extend(["", "【文件清单】"])
    for item in summary["results"]:
        lines.append(f"{item['index']}. [{item['status']}] {item['name']}\n   {item['note']}")
    lines.extend(["", "【启动时的审核要求】"])
    for number in (3, 4, 23, 25):
        lines.append(f"第{number}栏：")
        lines.append(summary["requirements"].get(number, "已停用，未审核。"))
    lines.extend(["", "本结果仅反映当前必含文字规则，不代表整份运单的全面审核。"])
    return "\n".join(lines)
