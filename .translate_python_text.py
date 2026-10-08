from __future__ import annotations

import io
import json
import difflib
import ast
import re
import subprocess
import tokenize
from pathlib import Path

from argostranslate import translate


ROOT = Path(__file__).resolve().parent
CJK = re.compile(r"[\u3400-\u9fff]")
STRING_TOKEN = re.compile(
    r"(?is)^(?P<prefix>[rubf]*)?(?P<quote>'''|\"\"\"|'|\")(?P<body>.*)(?P=quote)$"
)
PROTECT = re.compile(
    r"`[^`]+`|\{[^{}\n]+\}|https?://\S+|\b[A-Za-z][A-Za-z0-9]*(?:[._/:-][A-Za-z0-9]+)+\b|\b[A-Z][A-Z0-9_]{2,}\b"
)
CACHE_PATH = Path("/tmp/sca_argos_runtime_cache.json")
GLOSSARY = {
    "单企业": "single-enterprise",
    "多企业": "multi-enterprise",
    "企业": "enterprise",
    "部门": "department",
    "轮次": "round",
    "复盘": "review",
    "仓容": "warehouse capacity",
    "排产": "production scheduling",
    "落盘": "persist",
    "补货": "replenishment",
    "履约": "fulfillment",
    "在途": "in transit",
    "原料": "raw material",
    "产能": "capacity",
    "交易所": "exchange",
    "工作流": "workflow",
    "信号量": "semaphore",
}


def tracked_python_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def protect(text: str) -> tuple[str, dict[str, str]]:
    values: dict[str, str] = {}

    def reserve(value: str) -> str:
        key = f"<x{len(values)}/>"
        values[key] = value
        return key

    for source, target in sorted(GLOSSARY.items(), key=lambda item: -len(item[0])):
        text = text.replace(source, reserve(target))

    def replace(match: re.Match[str]) -> str:
        return reserve(match.group(0))

    return PROTECT.sub(replace, text), values


def restore(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        text = text.replace(key, value)
    return text


def docstring_positions(source: str) -> set[tuple[int, int]]:
    positions: set[tuple[int, int]] = set()
    tree = ast.parse(source)
    nodes = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, nodes) or not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            positions.add((first.value.lineno, first.value.col_offset))
    return positions


def load_cache() -> dict[str, str]:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def translate_segment(text: str, cache: dict[str, str]) -> str:
    if text in cache:
        return cache[text]
    safe, values = protect(text)
    translated = translate.translate(safe, "zh", "en").strip()
    translated = restore(translated, values)
    cache[text] = translated
    if len(cache) % 50 == 0:
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"translated {len(cache)} unique segments", flush=True)
    return translated


def translate_lines(text: str, cache: dict[str, str]) -> str:
    output: list[str] = []
    for line in text.splitlines(keepends=True):
        ending = "\n" if line.endswith("\n") else ""
        content = line[:-1] if ending else line
        leading = content[: len(content) - len(content.lstrip())]
        trailing = content[len(content.rstrip()) :]
        body = content.strip()
        if CJK.search(body):
            body = translate_segment(body, cache)
        output.append(leading + body + trailing + ending)
    return "".join(output)


def line_offsets(source: str) -> list[int]:
    offsets = [0]
    offsets.extend(match.end() for match in re.finditer("\n", source))
    return offsets


def absolute_offset(offsets: list[int], position: tuple[int, int]) -> int:
    row, column = position
    return offsets[row - 1] + column


def escape_quote(text: str, quote: str) -> str:
    if len(quote) != 1:
        return text
    return re.sub(rf"(?<!\\){re.escape(quote)}", rf"\\{quote}", text)


def rewrite(path: Path, cache: dict[str, str]) -> bool:
    source = path.read_text(encoding="utf-8")
    if not CJK.search(source):
        return False
    offsets = line_offsets(source)
    docs = docstring_positions(source)
    replacements: list[tuple[int, int, str]] = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        replacement: str | None = None
        if (
            token.type == tokenize.STRING
            and token.start not in docs
            and CJK.search(token.string)
        ):
            match = STRING_TOKEN.match(token.string)
            if match:
                prefix = match.group("prefix") or ""
                quote = match.group("quote")
                body = escape_quote(translate_lines(match.group("body"), cache), quote)
                replacement = prefix + quote + body + quote
        if replacement is not None:
            replacements.append(
                (
                    absolute_offset(offsets, token.start),
                    absolute_offset(offsets, token.end),
                    replacement,
                )
            )
    for start, end, replacement in reversed(replacements):
        source = source[:start] + replacement + source[end:]
    relative = path.relative_to(ROOT)
    patch_dir = Path("/tmp/sca-python-runtime-patches")
    patch_dir.mkdir(parents=True, exist_ok=True)
    diff = list(
        difflib.unified_diff(
            path.read_text(encoding="utf-8").splitlines(),
            source.splitlines(),
            fromfile=str(relative),
            tofile=str(relative),
            lineterm="",
        )
    )
    patch_body = "\n".join(diff[2:])
    patch_text = (
        "*** Begin Patch\n"
        f"*** Update File: .agents/anonymous-release/{relative}\n"
        f"{patch_body}\n"
        "*** End Patch\n"
    )
    patch_name = str(relative).replace("/", "__") + ".patch"
    (patch_dir / patch_name).write_text(patch_text, encoding="utf-8")
    return True


def main() -> None:
    cache = load_cache()
    changed = 0
    for path in tracked_python_files():
        if rewrite(path, cache):
            changed += 1
            print(f"rewrote {path.relative_to(ROOT)}", flush=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"completed {changed} Python files", flush=True)


if __name__ == "__main__":
    main()
