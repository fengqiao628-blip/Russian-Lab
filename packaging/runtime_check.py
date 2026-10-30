"""Opt-in integration check of the frozen app; no effect on normal startup."""

import json
import os
from pathlib import Path
import sys
import traceback
from zipfile import ZipFile


def run():
    config = json.loads(os.environ["WAYBILL_SELF_CHECK"])
    report_path = Path(config["report"])
    report_path.parent.mkdir(parents=True, exist_ok=True)

    def write_report(result):
        temporary = report_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(report_path)

    try:
        os.environ["QT_QPA_PLATFORM"] = "offscreen"
        from PySide6.QtCore import qVersion
        from PySide6.QtWidgets import QApplication
        from batch_review import BatchReviewWorker
        from field_extractor import extract_review_fields
        from main_window import MainWindow
        from pdf_reader import read_first_page
        from reviewer import compare_field

        if not getattr(sys, "frozen", False):
            raise RuntimeError("This check must run from the packaged executable.")
        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        window = MainWindow()
        window.show()
        app.processEvents()
        requirements = {int(number): text for number, text in config["requirements"].items()}
        spot_checks = []
        with ZipFile(config["zip_path"]) as archive:
            entries = [item for item in archive.infolist()
                       if not item.is_dir() and item.filename.lower().endswith(".pdf")]
            for index in config.get("sample_indices", [1]):
                data = archive.read(entries[index - 1])
                page_count, text = read_first_page(data)
                fields = extract_review_fields(data, requirements)
                if not text or page_count < 1:
                    raise RuntimeError(f"Sample {index}: no readable page text.")
                if any(compare_field(fields[number], requirement)["status"] != "全部匹配"
                       for number, requirement in requirements.items()):
                    raise RuntimeError(f"Sample {index}: expected requirements did not match.")
                number = next(iter(requirements))
                if compare_field(fields[number], "__WAYBILL_MUST_NOT_MATCH_749F0D__")["status"] == "全部匹配":
                    raise RuntimeError("Negative matching check unexpectedly passed.")
                spot_checks.append({"index": index, "pages": page_count, "text_characters": len(text),
                                    "field_characters": {str(key): len(value) for key, value in fields.items()}})

        result = {"status": "running", "frozen": True, "qt_version": qVersion(),
                  "window_initialized": True, "spot_checks": spot_checks, "negative_match_check": "passed"}
        write_report(result)
        if config.get("batch", True):
            summaries = []
            worker = BatchReviewWorker(config["zip_path"], requirements)
            worker.completed.connect(summaries.append)
            worker.finished.connect(app.quit)

            def progress(done, total, message):
                write_report({**result, "processed": done, "total": total})

            worker.progress.connect(progress)
            worker.start()
            app.exec()
            worker.wait()
            if not summaries:
                raise RuntimeError("Batch did not return a summary.")
            summary = summaries[0]
            result["batch"] = {key: summary[key] for key in
                               ("total", "processed", "remaining", "matched", "needs_review", "failed", "cancelled", "error")}
            if (summary["error"] or summary["cancelled"] or summary["failed"]
                    or summary["needs_review"] or summary["remaining"]
                    or summary["matched"] != len(entries)):
                raise RuntimeError("Batch results did not match the expected complete passing fixture.")
        window.close()
        result["status"] = "passed"
        write_report(result)
        return 0
    except Exception:
        write_report({"status": "failed", "error": traceback.format_exc()})
        return 1
