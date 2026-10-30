"""简单的必含文字检查：每行要求都应出现在对应栏，不解释自然语言。"""

import re
import unicodedata


def normalize_text(text):
    """统一兼容字符、大小写和连续空白，保留具体文字与数字。"""
    text = unicodedata.normalize("NFKC", text).casefold()
    # 换行、制表符、连续空格都变为一个空格，不拼接相邻编号。
    return re.sub(r"\s+", " ", text).strip()


def split_requirements(text):
    """每个非空行是一条要求，保留原来的文字用于显示。"""
    return [line.strip() for line in text.splitlines() if normalize_text(line)]


def compare_field(actual_text, requirement_text):
    """返回本栏状态、匹配要求、未匹配要求。空要求不能算匹配。"""
    requirements = split_requirements(requirement_text)
    result = {"status": "未填写要求", "matched": [], "unmatched": []}
    if not requirements:
        return result

    actual = normalize_text(actual_text)
    if not actual:
        result["status"] = "未提取到文字"
        result["unmatched"] = requirements
        return result

    for requirement in requirements:
        expected = normalize_text(requirement)
        # 要求按普通文字处理，括号、加号等不会被当作正则表达式。
        pattern = re.escape(expected)
        # 数字开头/结尾的要求不得命中更长编号中的一段数字。
        if expected[0].isdigit():
            pattern = r"(?<!\d)" + pattern
        if expected[-1].isdigit():
            pattern += r"(?!\d)"
        if re.search(pattern, actual):
            result["matched"].append(requirement)
        else:
            result["unmatched"].append(requirement)

    result["status"] = "存在未匹配项" if result["unmatched"] else "全部匹配"
    return result


def build_review_report(source, scope, fields, requirements):
    """把检查结果整理为文字报告；requirements 只包含启用栏。"""
    if not requirements:
        raise ValueError("请至少启用一个审核栏。")
    checks = {
        number: compare_field(fields.get(number, ""), requirement)
        for number, requirement in requirements.items()
    }
    matched_fields = sum(check["status"] == "全部匹配" for check in checks.values())
    if any(check["status"] == "未填写要求" for check in checks.values()):
        conclusion = "未完成检查：有启用栏未填写要求。"
    elif matched_fields == len(checks):
        conclusion = "本次必含文字规则全部匹配。"
    else:
        conclusion = "有未匹配要求或未提取到文字的栏位，请人工复核。"

    lines = [
        "【单份运单必含文字检查】",
        f"文件：{source}",
        f"范围：{scope}",
        f"汇总：启用 {len(checks)} 栏，全部匹配 {matched_fields} 栏，待处理 {len(checks)-matched_fields} 栏。",
        f"结论：{conclusion}",
        "规则：每个非空行必须出现在对应栏；统一大小写和连续空白。",
    ]
    for number in (3, 4, 23, 25):
        lines.append("")
        if number not in checks:
            lines.append(f"第{number}栏：已停用，未审核。")
            continue
        check = checks[number]
        count = len(check["matched"]) + len(check["unmatched"])
        lines.append(f"第{number}栏：{check['status']}（已匹配 {len(check['matched'])}/{count} 条）")
        if check["status"] == "未填写要求":
            lines.append("请填写本栏必须包含的原文或编号，每行一条。")
        if check["unmatched"]:
            lines.append("未匹配要求（可能缺少或格式不同，请对照原文）：")
            for requirement in check["unmatched"]:
                lines.append(f"  - {requirement}")
        lines.append("本栏提取原文：")
        lines.append(fields.get(number, "") or "（没有提取到文字，无法据此确认要求满足）")

    lines.extend(["", "本结果仅反映本次必含文字规则，不代表整份运单的全面审核。"])
    return "\n".join(lines)
