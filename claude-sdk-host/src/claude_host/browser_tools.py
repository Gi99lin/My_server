"""Framework-neutral browser toolkit for headless Chromium automation.

Provenance:
Adapted from /Users/ivanakimkin/Projects/ai-testcase-generator/test_importer_web/backend/src/tms/agents/sdk_runner/browser_tools.py.
Preserves the exact nine operations, input schemas, serialized execution, same-origin checks,
named secret typing, echo redaction, and masked evidence handling.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import Awaitable, Callable
from typing import Any

from .browser import (
    CRASH_MARKERS,
    BrowserSession,
    BrowserUnavailable,
    echo_variants,
    split_address,
    stand_url_refusal,
)
from .credentials import CredentialNotFound, StandRunnerAccess
from .evidence import EvidenceRejected, EvidenceSink
from .submission import ToolOutput, ToolSpec

SECRET_REFUSAL = "Вложение скрыто: в нём оказался секрет стенда"
BROWSER_CRASH = "Сбой браузера"
NAVIGATION_REFUSAL = "Переход запрещён"

MAX_RESULT_CHARS = 16_000
MAX_ERROR_CHARS = 400
SECRET_FIELDS_KEPT = 8
TOOL_TIMEOUT_SECONDS = 60
EVIDENCE_KINDS = ("screenshot", "console", "dom")
KIND_LABELS = {"screenshot": "скриншот", "console": "журнал консоли", "dom": "снимок DOM"}
KIND_FILENAMES = {"screenshot": "screenshot.png", "console": "console.log", "dom": "dom.html"}
LOCATOR_KEYS = ("role", "text", "label", "placeholder", "selector")
PASSWORD_NAME = "PASSWORD"
PASSWORD_FIELD_ONLY = "Пароль можно вводить только в поле пароля (input type=password)"
HIDDEN = "[скрыто]"


class ToolRefusal(Exception):
    """A refusal the model reads as the tool's answer; its text is the message."""


TARGET_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": (
        "Как найти элемент на странице: ровно один способ из role (с необязательным name), text, label, placeholder, "
        "selector. Роли и имена берите из снимка страницы. nth — номер среди нескольких подходящих (с нуля)."
    ),
    "properties": {
        "role": {"type": "string", "description": "Роль элемента, например button, link, textbox, combobox, checkbox"},
        "name": {"type": "string", "description": "Доступное имя элемента (только вместе с role)"},
        "text": {"type": "string", "description": "Видимый текст элемента"},
        "label": {"type": "string", "description": "Подпись поля ввода"},
        "placeholder": {"type": "string", "description": "Подсказка внутри поля"},
        "selector": {"type": "string", "description": "CSS-селектор, если иначе элемент не найти"},
        "nth": {"type": "integer", "minimum": 0, "description": "Номер среди нескольких подходящих, с нуля"},
    },
    "additionalProperties": False,
}


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        "open_url",
        "Открывает адрес стенда: полный адрес или путь от адреса стенда (например /login). Другие адреса запрещены.",
        _schema({"url": {"type": "string", "description": "Адрес или путь на стенде"}}, ["url"]),
    ),
    ToolSpec(
        "snapshot",
        "Снимок текущей страницы в виде дерева доступности: заголовки, поля, кнопки, ссылки и их имена. "
        "Это ваши глаза: делайте снимок перед действием и после него. Картинок вы не получаете.",
        _schema({}, []),
    ),
    ToolSpec(
        "click",
        "Нажимает на элемент страницы (кнопку, ссылку, флажок).",
        _schema({"target": TARGET_SCHEMA}, ["target"]),
    ),
    ToolSpec(
        "type_text",
        "Вводит обычный текст в поле (прежнее значение заменяется). Для логина и пароля стенда не подходит: "
        "используйте type_stand_secret. submit=true нажимает Enter после ввода.",
        _schema(
            {
                "target": TARGET_SCHEMA,
                "value": {"type": "string", "description": "Вводимый текст"},
                "submit": {"type": "boolean", "description": "Нажать Enter после ввода"},
            },
            ["target", "value"],
        ),
    ),
    ToolSpec(
        "type_stand_secret",
        "Вводит в поле учётные данные стенда набора этого прогона по имени: LOGIN — логин, PASSWORD — пароль, "
        "другие имена — только если их называет спецификация. Значение вы не получаете: ответ только "
        "говорит, что оно введено.",
        _schema(
            {
                "field": {**TARGET_SCHEMA, "description": "Поле ввода: способ поиска, как у target"},
                "name": {"type": "string", "description": "Имя данных: LOGIN, PASSWORD"},
            },
            ["field", "name"],
        ),
    ),
    ToolSpec(
        "press_key",
        "Нажимает клавишу или сочетание (Enter, Tab, Escape, Control+A). С target — на этом элементе, без — на странице.",
        _schema(
            {"key": {"type": "string", "description": "Клавиша, например Enter"}, "target": TARGET_SCHEMA}, ["key"]
        ),
    ),
    ToolSpec(
        "select_option",
        "Выбирает пункт выпадающего списка по его тексту или значению.",
        _schema(
            {"target": TARGET_SCHEMA, "option": {"type": "string", "description": "Текст или значение пункта"}},
            ["target", "option"],
        ),
    ),
    ToolSpec(
        "wait",
        "Ждёт: пока на странице появится text (не дольше seconds, по умолчанию 10 с) или просто seconds секунд (до 10).",
        _schema(
            {
                "text": {"type": "string", "description": "Текст, появления которого нужно дождаться"},
                "seconds": {"type": "number", "minimum": 0, "maximum": 10, "description": "Секунды ожидания"},
            },
            [],
        ),
    ),
    ToolSpec(
        "attach_evidence",
        "Прикладывает доказательство к шагу, у которого уже записан результат (сначала record_step): kind — screenshot "
        "(скриншот страницы), console (журнал консоли), dom (снимок DOM). Файл вы не получаете и не передаёте.",
        _schema(
            {
                "point_id": {"type": "string"},
                "step_id": {"type": "string"},
                "kind": {"type": "string", "enum": list(EVIDENCE_KINDS)},
            },
            ["point_id", "step_id", "kind"],
        ),
    ),
)


def _describe(target: dict[str, Any]) -> str:
    parts = [f'{key}="{target[key]}"' for key in (*LOCATOR_KEYS, "name") if target.get(key) not in (None, "")]
    return " ".join(parts) or "элемент"


def _text_arg(arguments: dict[str, Any], key: str, *, required: bool = True, limit: int = 4000) -> str | None:
    value = arguments.get(key)
    if value is None:
        if required:
            raise ToolRefusal(f"{key}: обязательное поле")
        return None
    if not isinstance(value, str):
        raise ToolRefusal(f"{key}: нужна строка")
    if required and not value.strip():
        raise ToolRefusal(f"{key}: обязательное поле")
    if len(value) > limit:
        raise ToolRefusal(f"{key}: не больше {limit} символов")
    return value


def _target_arg(arguments: dict[str, Any], key: str = "target") -> dict[str, Any]:
    target = arguments.get(key)
    if not isinstance(target, dict):
        raise ToolRefusal(f"{key}: нужен объект с одним способом поиска элемента")
    unknown = set(target) - {*LOCATOR_KEYS, "name", "nth"}
    if unknown:
        raise ToolRefusal(f"{key}: неизвестные поля {', '.join(sorted(map(str, unknown)))}")
    used = [name for name in LOCATOR_KEYS if target.get(name) not in (None, "")]
    if len(used) != 1:
        raise ToolRefusal(f"{key}: укажите ровно один способ найти элемент: role (с name), text, label, placeholder или selector")
    if any(not isinstance(target[name], str) for name in used):
        raise ToolRefusal(f"{key}.{used[0]}: нужна строка")
    if target.get("name") not in (None, "") and used[0] != "role":
        raise ToolRefusal(f"{key}.name: имя задаётся только вместе с role")
    nth = target.get("nth")
    if nth is not None and (isinstance(nth, bool) or not isinstance(nth, int) or nth < 0):
        raise ToolRefusal(f"{key}.nth: нужно целое число от 0")
    return target


class BrowserToolkit:
    """The tool set over one browser. Calls are serialized: the browser has one page and one pair of hands."""

    def __init__(
        self,
        stand: StandRunnerAccess,
        evidence: EvidenceSink | None = None,
        *,
        session: BrowserSession | None = None,
        action_timeout_ms: int = 10_000,
        check_active_cb: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._stand = stand
        self._evidence = evidence
        self._timeout_ms = action_timeout_ms
        self._check_active_cb = check_active_cb

        self._address, basic_auth = split_address(stand.address)
        self.session = session or BrowserSession(
            self._address, action_timeout_ms=action_timeout_ms, http_credentials=basic_auth
        )
        self._lock = asyncio.Lock()
        self._typed_echoes: set[str] = set()
        for part in basic_auth or ():
            self._typed_echoes |= echo_variants(part)

        self._handlers: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {
            "open_url": self._open_url,
            "snapshot": self._snapshot,
            "click": self._click,
            "type_text": self._type_text,
            "type_stand_secret": self._type_stand_secret,
            "press_key": self._press_key,
            "select_option": self._select_option,
            "wait": self._wait,
            "attach_evidence": self._attach_evidence,
        }

    async def aclose(self) -> None:
        await self.session.reset()

    async def call(self, name: str, arguments: dict[str, Any] | None = None) -> ToolOutput:
        arguments = arguments if isinstance(arguments, dict) else {}
        handler = self._handlers.get(name)
        async with self._lock:
            try:
                if self._check_active_cb is not None:
                    await self._check_active_cb()

                if handler is None:
                    raise ToolRefusal(f"Неизвестный инструмент: {name}")
                if self.session.broken():
                    await self.session.reset()
                    raise ToolRefusal(self._crash_message())
                text = await asyncio.wait_for(handler(arguments), timeout=TOOL_TIMEOUT_SECONDS)
                result = ToolOutput(text)
            except ToolRefusal as refusal:
                result = ToolOutput(str(refusal), True)
            except BrowserUnavailable:
                result = ToolOutput("Не удалось запустить браузер: повторите вызов, а при повторе передайте тест-поинт человеку", True)
            except Exception as error:
                result = ToolOutput(await self._failure(error), True)
        return ToolOutput(self._shape(result.text), result.is_error)

    def _shape(self, text: str) -> str:
        """Every result passes the stand's redaction and a size limit, whatever produced it."""
        text = self._stand.redact_text(text)
        for echo in self._typed_echoes:
            text = text.replace(echo, HIDDEN)
        if len(text) > MAX_RESULT_CHARS:
            text = text[:MAX_RESULT_CHARS] + "\n… (обрезано)"
        return text

    @staticmethod
    def _crash_message() -> str:
        return f"{BROWSER_CRASH}: действие не выполнено. Открыт новый браузер без сессии: войдите на стенд заново."

    async def _failure(self, error: Exception) -> str:
        """A tool failure in plain words. Stack traces and page contents never reach the model."""
        if isinstance(error, CredentialNotFound):
            return str(error)
        detail = str(getattr(error, "message", None) or error)
        lowered = detail.lower()
        if type(error).__name__ == "TargetClosedError" or any(marker in lowered for marker in CRASH_MARKERS):
            await self.session.reset()
            return self._crash_message()
        if type(error).__name__ == "TimeoutError" or "timeout" in lowered:
            return f"Превышено время ожидания ({self._timeout_ms // 1000} с): действие не удалось выполнить на этой странице"
        first = detail.strip().splitlines()[0] if detail.strip() else type(error).__name__
        first = re.sub(r"^[A-Za-z]+\.[A-Za-z_]+: (Error: )?", "", first)
        return f"Не удалось выполнить действие: {first[:MAX_ERROR_CHARS]}"

    async def _page(self) -> Any:
        return await self.session.ensure_page()

    def _holds_secret(self, data: bytes) -> bool:
        """The stand's own check, and the echoes of the values this toolkit typed."""
        if self._stand.contains_sensitive(data):
            return True
        return any(echo.encode() in data for echo in self._typed_echoes)

    def _locator(self, page: Any, target: dict[str, Any]) -> Any:
        if target.get("role"):
            return page.get_by_role(target["role"], name=target.get("name") or None)
        if target.get("text"):
            return page.get_by_text(target["text"])
        if target.get("label"):
            return page.get_by_label(target["label"])
        if target.get("placeholder"):
            return page.get_by_placeholder(target["placeholder"])
        return page.locator(target["selector"])

    async def _resolve(self, page: Any, target: dict[str, Any]) -> Any:
        locator = self._locator(page, target)
        if await locator.count() == 0:
            try:
                await locator.first.wait_for(state="attached", timeout=self._timeout_ms)
            except Exception:
                raise ToolRefusal(f"Элемент не найден: {_describe(target)}") from None
        count = await locator.count()
        nth = target.get("nth")
        if nth is not None:
            if nth >= count:
                raise ToolRefusal(f"nth: подходящих элементов {count}: {_describe(target)}")
            return locator.nth(nth)
        if count > 1:
            raise ToolRefusal(f"Подходит {count} элементов: {_describe(target)}. Уточните name или nth")
        return locator

    async def _settle(self, page: Any, blocked_before: int) -> None:
        with contextlib.suppress(Exception):
            await page.wait_for_load_state("domcontentloaded", timeout=3000)
        self._refuse_if_navigation_was_blocked(page, blocked_before)

    def _refuse_if_navigation_was_blocked(self, page: Any, blocked_before: int) -> None:
        if len(self.session.blocked) > blocked_before:
            raise ToolRefusal(
                f"{NAVIGATION_REFUSAL}: страница пыталась открыть адрес вне стенда ({self.session.blocked[-1]}). "
                f"Браузер остался на {page.url}"
            )

    async def _where(self, page: Any) -> str:
        title = ""
        with contextlib.suppress(Exception):
            title = await page.title()
        return f"Страница: {page.url} — «{title}»"

    async def _open_url(self, arguments: dict[str, Any]) -> str:
        raw = _text_arg(arguments, "url", limit=2000).strip()
        absolute = (
            urljoin(self._address.rstrip("/") + "/", raw)
            if raw.startswith("/") and not raw.startswith("//")
            else raw
        )
        refusal = stand_url_refusal(self._address, absolute)
        if refusal:
            raise ToolRefusal(refusal)
        page = await self._page()
        before = len(self.session.blocked)
        try:
            response = await page.goto(absolute, wait_until="domcontentloaded")
        except Exception:
            self._refuse_if_navigation_was_blocked(page, before)
            raise
        self._refuse_if_navigation_was_blocked(page, before)
        status = f" (ответ {response.status})" if response is not None and response.status >= 400 else ""
        return f"Открыто{status}. {await self._where(page)}"

    async def _snapshot(self, arguments: dict[str, Any]) -> str:
        page = await self._page()
        text = await page.locator("body").aria_snapshot()
        if self._holds_secret(text.encode()):
            raise ToolRefusal(SECRET_REFUSAL)
        return text.strip() or "(страница пуста)"

    async def _click(self, arguments: dict[str, Any]) -> str:
        target = _target_arg(arguments)
        page = await self._page()
        element = await self._resolve(page, target)
        before = len(self.session.blocked)
        await element.click()
        await self._settle(page, before)
        return f"Нажато: {_describe(target)}. {await self._where(page)}"

    async def _type_text(self, arguments: dict[str, Any]) -> str:
        target = _target_arg(arguments)
        value = _text_arg(arguments, "value", required=False, limit=4000) or ""
        submit = arguments.get("submit", False)
        if not isinstance(submit, bool):
            raise ToolRefusal("submit: нужно true или false")
        page = await self._page()
        element = await self._resolve(page, target)
        before = len(self.session.blocked)
        await element.fill(value)
        if submit:
            await element.press("Enter")
            await self._settle(page, before)
        return f"Введён текст в поле {_describe(target)}" + (" и нажат Enter." if submit else ".")

    async def _type_stand_secret(self, arguments: dict[str, Any]) -> str:
        field = _target_arg(arguments, "field")
        name = _text_arg(arguments, "name", limit=64)
        page = await self._page()
        element = await self._resolve(page, field)
        if name == PASSWORD_NAME and not await element.evaluate(
            "el => el instanceof HTMLInputElement && el.type === 'password'"
        ):
            raise ToolRefusal(PASSWORD_FIELD_ONLY)
        typed: list[str] = []

        async def fill(value: str) -> None:
            typed.append(value)
            await element.fill(value)

        try:
            await self._stand.type_named_value(self._stand.credential_key, name, fill)
        finally:
            for value in typed:
                self._typed_echoes |= echo_variants(value)
        self.session.remember_secret_field(element)
        return f"Введено значение «{name}» в поле {_describe(field)}."

    async def _press_key(self, arguments: dict[str, Any]) -> str:
        key = _text_arg(arguments, "key", limit=40)
        page = await self._page()
        before = len(self.session.blocked)
        if arguments.get("target") is not None:
            element = await self._resolve(page, _target_arg(arguments))
            await element.press(key)
        else:
            await page.keyboard.press(key)
        await self._settle(page, before)
        return f"Нажата клавиша {key}. {await self._where(page)}"

    async def _select_option(self, arguments: dict[str, Any]) -> str:
        target = _target_arg(arguments)
        option = _text_arg(arguments, "option", limit=500)
        page = await self._page()
        element = await self._resolve(page, target)
        chosen = await element.select_option(option)
        return f"Выбрано в {_describe(target)}: {', '.join(chosen) if chosen else option}."

    async def _wait(self, arguments: dict[str, Any]) -> str:
        text = _text_arg(arguments, "text", required=False, limit=500)
        seconds = arguments.get("seconds")
        if seconds is not None and (isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 <= seconds <= 10):
            raise ToolRefusal("seconds: допустимо от 0 до 10")
        if text is None and seconds is None:
            raise ToolRefusal("wait: укажите text или seconds")
        page = await self._page()
        if text is None:
            await asyncio.sleep(seconds)
            return f"Прошло {seconds} с."
        limit = seconds if seconds is not None else 10
        try:
            await page.get_by_text(text).first.wait_for(state="visible", timeout=limit * 1000)
        except Exception:
            raise ToolRefusal(f"Текст не появился за {limit:g} с: {text}") from None
        return f"Текст появился: {text}"

    async def _capture(self, page: Any, kind: str) -> bytes:
        if kind == "screenshot":
            masks = [field for field in self.session.secret_fields]
            return await page.screenshot(type="png", mask=masks, animations="disabled")
        if kind == "console":
            lines = list(self.session.console) or ["(в консоли ничего нет)"]
            return "\n".join(lines).encode()
        return (await page.content()).encode()

    async def _attach_evidence(self, arguments: dict[str, Any]) -> str:
        point_id = _text_arg(arguments, "point_id", limit=64)
        step_id = _text_arg(arguments, "step_id", limit=64)
        kind = _text_arg(arguments, "kind", limit=16)
        if kind not in EVIDENCE_KINDS:
            raise ToolRefusal("kind: допустимо screenshot, console, dom")
        if self._evidence is None:
            raise ToolRefusal("Доказательства к шагам в этом прогоне не подключены")
        page = await self._page()
        data = await self._capture(page, kind)
        if self._holds_secret(data):
            raise ToolRefusal(SECRET_REFUSAL)
        try:
            await self._evidence.attach(
                point_id=point_id, step_id=step_id, kind=kind, data=data, filename=KIND_FILENAMES[kind]
            )
        except EvidenceRejected as rejected:
            raise ToolRefusal(str(rejected)) from None
        return f"Приложено к шагу: {KIND_LABELS[kind]}."
