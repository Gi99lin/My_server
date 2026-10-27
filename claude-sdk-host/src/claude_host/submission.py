"""Pure test source submission validator for authoring sessions.

Provenance:
Adapted from /Users/ivanakimkin/Projects/ai-testcase-generator/test_importer_web/backend/src/tms/agents/sdk_author/submission.py
and src/tms/agents/authoring/worker.py.
Preserves exact pure source verification rules without TMS backend, database or keyring dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from .browser import echo_variants, split_address

if TYPE_CHECKING:
    from .credentials import StandRunnerAccess

ALREADY_SUBMITTED = "Тест уже передан: больше ничего не вызывайте и закончите одной строкой."
ACCEPTED = "Тест принят. Больше ничего не вызывайте: закончите работу одной строкой."

HIDDEN = "[скрыто]"
MIN_ECHO_LENGTH = 6
MAX_SOURCE_CHARS = 60_000
TOO_LARGE = f"Файл теста слишком большой: не больше {MAX_SOURCE_CHARS:,} символов.".replace(",", " ")
NO_PLAYWRIGHT = "Не удалось создать тест Playwright."
NO_CASE_ID = "В тесте не указан идентификатор тест-кейса."

_QUOTED = r"""(?P<q>['"`])(?P<v>(?:\\.|(?!(?P=q)).)+)(?P=q)"""
_CREDENTIAL_WORDS = r"(?:password|passwd|pwd|passphrase|secret|token|api_?key|credentials?)"

_CREDENTIAL_ASSIGNMENT = re.compile(
    r"(?<![\w$])[\w$]*" + _CREDENTIAL_WORDS + r"(?![\w$])['\"]?\s*"
    r"(?:\??\s*:\s*[A-Za-z_][\w$<>\[\]|. ]*?)?\s*[:=]\s*" + _QUOTED,
    re.IGNORECASE,
)

_ENVIRONMENT_FALLBACK = re.compile(
    r"process\.env(?:\.STAND_[\w$]*|\[[^\]]*STAND_[^\]]*\])\s*(?:\|\||\?\?)\s*" + _QUOTED
)

_PASSWORD_FIELD_FILL = re.compile(
    r"(?:password|passwd|парол)(?:(?!\bawait\b|\.fill\(|\.click\(|;).){0,160}?"
    r"\.(?:fill|type|pressSequentially)\s*\(\s*" + _QUOTED,
    re.IGNORECASE | re.DOTALL,
)

_STAND_PASSWORD_READ = re.compile(r"STAND_[^'\"`\n]*?PASSWORD")

_FIXED_WAIT = re.compile(r"(?<![\w$])(?:waitForTimeout|sleep)\s*\(|(?<![\w$.])setTimeout\s*\(")

_WHOLE_ENVIRONMENT = re.compile(r"process\.env(?!\s*(?:\??\.\s*[A-Za-z_$]|\[))")

ALLOWED_MODULES = frozenset(
    {
        "@playwright/test", "playwright", "playwright-core",
        "fs", "fs/promises", "os", "path", "url", "child_process", "crypto", "util", "assert", "assert/strict",
        "buffer",
    }
)

_IMPORT_OR_EXPORT = re.compile(r"\b(import|export)\b")
_SIDE_EFFECT_IMPORT = re.compile(r"""\s*(?:type\s+)?['"]([^'"]+)['"]""")
_FROM_SPECIFIER = re.compile(r"""\bfrom\s*['"]([^'"]+)['"]""")
_REQUIRE_OR_IMPORT_CALL = re.compile(r"""(?<![\w$.])(?:require|import)\s*\(\s*['"]([^'"]+)['"]\s*\)""")
ARGUMENT_WINDOW = 400
MODULE_WINDOW = 4000

_DYNAMIC_MODULE = re.compile(r"""(?<![\w$.])(?:require|import)\s*\(\s*(?!['"])""")
_PROCESS_CALL = re.compile(r"(?<![\w$])(?:exec|execSync|execFile|spawn|spawnSync|fork)\s*\(")
_EXEC_FILE_SYNC = re.compile(r"(?<![\w$])execFileSync\s*\(")
_SIGN_IN_PROCESS = re.compile(r"""(?<![\w$])execFileSync\s*\(\s*process\.execPath\s*,\s*\[\s*['"]-e['"]""")
_EVALUATION = re.compile(r"(?<![\w$.])eval\s*\(|\bnew\s+Function\s*\(")
_NETWORK = re.compile(r"(?<![\w$.])fetch\s*\(|\bXMLHttpRequest\b|\bWebSocket\b|\bsendBeacon\b|\bEventSource\b")

_SECRET_READ = (
    r"process\.env(?:\.STAND_(?!URL(?![\w$]))[\w$]+|\[(?!\s*['\"`]STAND_URL['\"`]\s*\])[^\]]*STAND_[^\]]*\])"
)
_SECRET_READ_RE = re.compile(_SECRET_READ)
_TAINTED_NAME = re.compile(r"(?:const|let|var)\s+([\w$]+)\s*(?::[^=;]+?)?=\s*" + _SECRET_READ)

_SINK = re.compile(
    r"console\s*\.\s*\w+\s*\(|\.\s*attach\s*\(|\b(?:writeFile|appendFile)(?:Sync)?\s*\(|JSON\s*\.\s*stringify\s*\("
    r"|(?<![\w$.])expect\s*\(|\btest\s*\.\s*step\s*\(|\bnew\s+Error\s*\(|(?<![\w$.])Error\s*\("
)

ENVIRONMENT_REFUSAL = (
    "В тесте читается всё окружение (process.env целиком). Читайте переменные по имени: process.env.STAND_URL, "
    "process.env.STAND_{key}_LOGIN."
)
MODULE_REFUSAL = (
    "В тесте подключён недопустимый модуль. Допустимы @playwright/test, playwright-core и встроенные модули Node: "
    "fs, os, path, url, crypto, util, assert, buffer и child_process (только для входа по шаблону)."
)
PROCESS_REFUSAL = (
    "В тесте запускаются процессы или вычисляется код (child_process, eval, new Function). Допустим только вход по "
    "шаблону: execFileSync(process.execPath, ['-e', …])."
)
NETWORK_REFUSAL = (
    "В тесте есть прямой сетевой запрос (fetch, XMLHttpRequest, WebSocket, sendBeacon). Для запросов к API стенда "
    "используйте фикстуру request Playwright."
)
SECRET_OUTPUT_REFUSAL = (
    "Секрет из process.env передан в вывод, ошибку, шаг отчёта, вложение или файл (console, Error, test.step, expect, "
    "attach, writeFile). Секреты можно только вводить в поля: .fill(process.env.STAND_{key}_PASSWORD!)."
)


@dataclass(frozen=True)
class ToolOutput:
    text: str
    is_error: bool = False


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


SUBMIT_SPEC = ToolSpec(
    "submit_test",
    "Передаёт готовый файл теста: полный исходник одним файлом TypeScript для Playwright Test. Это единственный способ "
    "отдать результат: текст ответа не читается. Если сервер отказывает, в ответе причина: исправьте файл и вызовите "
    "снова. После того как тест принят, больше ничего не вызывайте.",
    {
        "type": "object",
        "properties": {"source": {"type": "string", "description": "Полный текст файла теста"}},
        "required": ["source"],
        "additionalProperties": False,
    },
)


def _secret_values(access: StandRunnerAccess | None) -> list[str]:
    if access is None:
        return []
    return [value for fields in access._values.values() for value in fields.values() if value]


def _secret_forms(access: StandRunnerAccess | None) -> list[str]:
    forms: set[str] = set()
    for value in _secret_values(access):
        forms.add(value)
        if len(value) >= MIN_ECHO_LENGTH:
            forms |= echo_variants(value)
    return sorted(forms, key=len, reverse=True)


def scrub_secrets(text: str, access: StandRunnerAccess | None) -> str:
    for form in _secret_forms(access):
        text = text.replace(form, HIDDEN)
    return text


def _holds_secret(source: str, access: StandRunnerAccess | None) -> bool:
    if access is None:
        return False
    return access.contains_sensitive(source.encode()) or any(form in source for form in _secret_forms(access))


def _code_only(source: str) -> str:
    out: list[str] = []
    index, size, quote = 0, len(source), None
    while index < size:
        char = source[index]
        if quote:
            out.append(char)
            if char == "\\" and index + 1 < size:
                out.append(source[index + 1])
                index += 2
                continue
            if char == quote:
                quote = None
            index += 1
        elif char in "'\"`":
            quote = char
            out.append(char)
            index += 1
        elif source.startswith("//", index):
            end = source.find("\n", index)
            end = size if end == -1 else end
            out.append(" " * (end - index))
            index = end
        elif source.startswith("/*", index):
            end = source.find("*/", index + 2)
            end = size if end == -1 else end + 2
            out.append(re.sub(r"[^\n]", " ", source[index:end]))
            index = end
        else:
            out.append(char)
            index += 1
    return "".join(out)


def _is_literal(match: re.Match) -> bool:
    return not (match.group("q") == "`" and "${" in match.group("v"))


def _credential_literal(code: str) -> bool:
    if any(_is_literal(match) for match in _CREDENTIAL_ASSIGNMENT.finditer(code)):
        return True
    if any(_is_literal(match) for match in _ENVIRONMENT_FALLBACK.finditer(code)):
        return True
    if any(_is_literal(match) for match in _PASSWORD_FIELD_FILL.finditer(code)):
        return not _STAND_PASSWORD_READ.search(code)
    return False


def _module_specifiers(code: str):
    for match in _IMPORT_OR_EXPORT.finditer(code):
        window = code[match.end() : match.end() + MODULE_WINDOW].split(";", 1)[0]
        found = _SIDE_EFFECT_IMPORT.match(window) if match.group(1) == "import" else None
        found = found or _FROM_SPECIFIER.search(window)
        if found:
            yield found.group(1)
    for match in _REQUIRE_OR_IMPORT_CALL.finditer(code):
        yield match.group(1)


def _module_refused(code: str) -> bool:
    if _DYNAMIC_MODULE.search(code):
        return True
    return any(
        not specifier.startswith(".") and specifier.removeprefix("node:") not in ALLOWED_MODULES
        for specifier in _module_specifiers(code)
    )


def _runs_code(code: str) -> bool:
    if _EVALUATION.search(code):
        return True
    if "child_process" not in code:
        return False
    return bool(_PROCESS_CALL.search(code)) or len(_EXEC_FILE_SYNC.findall(code)) != len(_SIGN_IN_PROCESS.findall(code))


def _arguments(code: str, start: int) -> str:
    depth, quote, index = 1, None, start
    stop = min(len(code), start + ARGUMENT_WINDOW)
    while index < stop:
        char = code[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return code[start:index]
        index += 1
    return code[start:stop]


def _secret_to_a_sink(code: str) -> bool:
    tainted = [re.compile(rf"(?<![\w$.]){re.escape(name)}(?![\w$])") for name in _TAINTED_NAME.findall(code)]
    for sink in _SINK.finditer(code):
        arguments = _arguments(code, sink.end())
        if _SECRET_READ_RE.search(arguments) or any(name.search(arguments) for name in tainted):
            return True
    return False


def _address_literals(access: StandRunnerAccess | None) -> list[str]:
    if access is None:
        return []
    try:
        clean, _basic = split_address(access.address)
        netloc = urlsplit(clean).netloc
    except ValueError:
        return []
    return [form for form in {clean.strip().rstrip("/"), netloc} if form]


def source_refusal(source: str | None, contract: dict | None = None, access: StandRunnerAccess | None = None) -> str | None:
    """Validate test source against pure constraints. Returns reason if refused, or None if acceptable."""
    contract = contract or {}
    if source and len(source) > MAX_SOURCE_CHARS:
        return TOO_LARGE
    if not source or "@playwright/test" not in source:
        return NO_PLAYWRIGHT

    case_id = contract.get("global_case_id") or contract.get("global_id")
    if case_id and str(case_id) not in source:
        return NO_CASE_ID

    key = (access.credential_key if access is not None else None) or contract.get("credential_key") or "<КЛЮЧ>"
    if _holds_secret(source, access):
        return (
            "В тесте найдено значение секрета стенда. Значения нельзя записывать в файл: читайте их из process.env — "
            f"STAND_URL, STAND_{key}_LOGIN, STAND_{key}_PASSWORD, STAND_{key}_<ИМЯ>."
        )

    code = _code_only(source)
    if _WHOLE_ENVIRONMENT.search(code):
        return ENVIRONMENT_REFUSAL.format(key=key)
    if _module_refused(code):
        return MODULE_REFUSAL
    if _runs_code(code):
        return PROCESS_REFUSAL
    if _NETWORK.search(code):
        return NETWORK_REFUSAL
    if _secret_to_a_sink(code):
        return SECRET_OUTPUT_REFUSAL.format(key=key)
    if _credential_literal(code):
        return (
            "В тесте логин, пароль или токен записаны литералом. Берите данные для входа из "
            f"process.env.STAND_{key}_LOGIN и process.env.STAND_{key}_PASSWORD, без значения по умолчанию."
        )
    if any(form in code for form in _address_literals(access)):
        return "В тесте записан адрес стенда. Берите его из process.env.STAND_URL."
    if _FIXED_WAIT.search(code):
        return (
            "В тесте есть фиксированная пауза (waitForTimeout, setTimeout, sleep). Ждите состояние страницы: "
            "expect(locator).toBeVisible(), toHaveText(…) и другие проверки с автоожиданием."
        )
    return None


class Submission:
    """Tracks source submission for authoring sessions.

    Accepts exactly one source. Repeated identical submissions are idempotent.
    Differing subsequent submissions are rejected.
    """

    def __init__(self, contract: dict | None, access: StandRunnerAccess | None) -> None:
        self._contract = contract or {}
        self._access = access
        self.source: str | None = None

    def submit(self, arguments: dict[str, Any]) -> ToolOutput:
        source = arguments.get("source") if isinstance(arguments, dict) else None
        if not isinstance(source, str) or not source.strip():
            return ToolOutput("source: нужен непустой текст файла теста", is_error=True)
        if len(source) > MAX_SOURCE_CHARS:
            return ToolOutput(f"source: файл не больше {MAX_SOURCE_CHARS} символов", is_error=True)

        if self.source is not None:
            if self.source == source:
                return ToolOutput(ACCEPTED, is_error=False)
            return ToolOutput(ALREADY_SUBMITTED, is_error=True)

        refusal = source_refusal(source, self._contract, self._access)
        if refusal:
            return ToolOutput(f"Тест не принят: {refusal}", is_error=True)

        self.source = source
        return ToolOutput(ACCEPTED, is_error=False)
