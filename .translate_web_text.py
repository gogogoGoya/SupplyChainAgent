from __future__ import annotations

import difflib
import json
import re
import subprocess
from pathlib import Path

from argostranslate import translate


ROOT = Path(__file__).resolve().parent
CJK = re.compile(r"[\u3400-\u9fff]")
STRING = re.compile(r"(?P<quote>['\"])(?P<body>(?:\\.|(?!\1).)*)(?P=quote)")
JSX_TEXT = re.compile(r">(?P<body>[^<]*[\u3400-\u9fff][^<]*)<")
CHINESE_RUN = re.compile(r"[\u3400-\u9fff][\u3400-\u9fff，。；：、（）！？“”‘’《》【】…· \t]*")
PROTECT = re.compile(r"\{[^{}\n]+\}|`[^`]+`|\b[A-Za-z][A-Za-z0-9]*(?:[._/:-][A-Za-z0-9]+)+\b|\b[A-Z][A-Z0-9_]{2,}\b")
CACHE_PATH = Path("/tmp/sca_argos_web_cache.json")
GLOSSARY = {
    "单企业": "single-enterprise",
    "多企业": "multi-enterprise",
    "企业": "enterprise",
    "部门": "department",
    "轮次": "round",
    "场景": "scenario",
    "实验": "experiment",
    "公地悲剧": "tragedy of the commons",
    "羊群效应": "herding effect",
    "牛鞭效应": "bullwhip effect",
    "蛛网模型": "cobweb model",
    "运行记录": "run records",
    "效果展示": "results",
    "订单": "order",
    "库存": "inventory",
    "现金": "cash",
    "产能": "capacity",
    "采购": "procurement",
    "生产": "production",
    "销售": "sales",
}


def reserve_text(text: str) -> tuple[str, dict[str, str]]:
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


def load_cache() -> dict[str, str]:
    if not CACHE_PATH.exists():
        return {}
    return json.loads(CACHE_PATH.read_text(encoding="utf-8"))


def translate_text(text: str, cache: dict[str, str]) -> str:
    if not CJK.search(text):
        return text
    if text in cache:
        return cache[text]
    leading = text[: len(text) - len(text.lstrip())]
    trailing = text[len(text.rstrip()) :]
    body = text.strip()
    safe, values = reserve_text(body)
    result = translate.translate(safe, "zh", "en").strip()
    for key, value in values.items():
        result = result.replace(key, value)
    cache[text] = leading + result + trailing
    if len(cache) % 50 == 0:
        CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"translated {len(cache)} web strings", flush=True)
    return cache[text]


def translate_line(line: str, cache: dict[str, str]) -> str:
    if not CJK.search(line):
        return line

    def string_repl(match: re.Match[str]) -> str:
        quote = match.group("quote")
        body = translate_text(match.group("body"), cache)
        body = re.sub(rf"(?<!\\){re.escape(quote)}", rf"\\{quote}", body)
        return quote + body + quote

    line = STRING.sub(string_repl, line)

    def jsx_repl(match: re.Match[str]) -> str:
        return ">" + translate_text(match.group("body"), cache) + "<"

    line = JSX_TEXT.sub(jsx_repl, line)

    if CJK.search(line):
        line = CHINESE_RUN.sub(lambda match: translate_text(match.group(0), cache), line)
    return line


def main() -> None:
    result = subprocess.run(
        ["git", "ls-files", "visualization/src/*.js", "visualization/src/*.jsx", "visualization/src/*.css", "visualization/*.html"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    cache = load_cache()
    patch_dir = Path("/tmp/sca-web-translation-patches")
    patch_dir.mkdir(parents=True, exist_ok=True)
    changed = 0
    for rel in result.stdout.splitlines():
        path = ROOT / rel
        old = path.read_text(encoding="utf-8")
        if not CJK.search(old):
            continue
        new = "".join(translate_line(line, cache) for line in old.splitlines(keepends=True))
        if new == old:
            continue
        diff = list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm=""))
        body = "\n".join("@@" if line.startswith("@@ ") else line for line in diff[2:])
        patch = (
            "*** Begin Patch\n"
            f"*** Update File: .agents/anonymous-release/{rel}\n"
            f"{body}\n"
            "*** End Patch\n"
        )
        name = rel.replace("/", "__") + ".patch"
        (patch_dir / name).write_text(patch, encoding="utf-8")
        changed += 1
        print(f"prepared {rel}", flush=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"prepared {changed} web patches", flush=True)


if __name__ == "__main__":
    main()
