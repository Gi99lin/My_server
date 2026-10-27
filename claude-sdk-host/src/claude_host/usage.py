"""Usage meter and token accounting for Claude Agent SDK runs.

Maintains message-ID deduplication across raw StreamEvent, AssistantMessage and
final ResultMessage without double counting turns or cumulative counters.
Emits normalized positive token deltas with agent budget (excludes cache reads)
and completion prompt tokens (includes cache reads).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _safe_int(value: Any) -> int:
    """Extract a positive non-boolean integer or return 0."""
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return 0


class UsageMeter:
    """Deduplicating usage tracker keyed by provider message ID.

    Maintains per-message maximum observations for streaming deltas and
    reconciles with final cumulative counters from ResultMessage.
    """

    def __init__(self, model: str | None = None) -> None:
        self.model = model
        # Map message_id -> (input, cache_creation, cache_read, output)
        self._seen_per_message: dict[str, tuple[int, int, int, int]] = {}
        self._current_msg_id: str | None = None

        self.total_input_tokens = 0
        self.total_cache_creation_input_tokens = 0
        self.total_cache_read_input_tokens = 0
        self.total_output_tokens = 0
        self.total_budget_tokens = 0
        self.total_completion_prompt_tokens = 0

        self._result_seen = False
        self._accounting_complete = False

    def observe(self, message: Any) -> list[dict[str, int]]:
        """Observe an incoming SDK message and return positive usage deltas.

        Supports StreamEvent, AssistantMessage, and ResultMessage (both SDK dataclasses
        and dict representations).
        """
        # 1. ResultMessage (final cumulative counters across the whole session)
        if hasattr(message, "subtype") and hasattr(message, "duration_ms"):
            usage = getattr(message, "usage", None)
            return self._observe_result_usage(usage)
        if isinstance(message, dict) and "subtype" in message and "duration_ms" in message:
            return self._observe_result_usage(message.get("usage"))

        # 2. StreamEvent (raw Anthropic API stream event)
        if hasattr(message, "event"):
            event = getattr(message, "event", None)
            uuid_val = getattr(message, "uuid", None)
            return self._observe_stream_event(event, uuid_val)
        if isinstance(message, dict) and "event" in message:
            return self._observe_stream_event(message.get("event"), message.get("uuid"))

        # 3. AssistantMessage (turn-level content and usage)
        if hasattr(message, "content") and hasattr(message, "usage"):
            msg_id = getattr(message, "message_id", None) or getattr(message, "uuid", None) or self._current_msg_id
            usage = getattr(message, "usage", None)
            return self._observe_message_usage(msg_id, usage)
        if isinstance(message, dict) and "content" in message:
            msg_id = message.get("message_id") or message.get("uuid") or self._current_msg_id
            return self._observe_message_usage(msg_id, message.get("usage"))

        return []

    def _observe_stream_event(self, event: Any, uuid_val: str | None) -> list[dict[str, int]]:
        if not isinstance(event, dict):
            return []

        event_type = event.get("type")
        if event_type == "message_start":
            msg = event.get("message", {})
            if isinstance(msg, dict):
                msg_id = msg.get("id") or uuid_val
                if msg_id:
                    self._current_msg_id = str(msg_id)
                usage = msg.get("usage")
                return self._observe_message_usage(self._current_msg_id, usage)

        elif event_type == "message_delta":
            msg_id = self._current_msg_id or uuid_val
            usage = event.get("usage")
            return self._observe_message_usage(msg_id, usage)

        return []

    def _observe_message_usage(self, msg_id: str | None, usage: Any) -> list[dict[str, int]]:
        if not isinstance(usage, dict):
            return []

        key = msg_id or self._current_msg_id or "anonymous"

        new_in = _safe_int(usage.get("input_tokens"))
        new_cc = _safe_int(usage.get("cache_creation_input_tokens"))
        new_cr = _safe_int(usage.get("cache_read_input_tokens"))
        new_out = _safe_int(usage.get("output_tokens"))

        seen_in, seen_cc, seen_cr, seen_out = self._seen_per_message.get(key, (0, 0, 0, 0))

        delta_in = max(0, new_in - seen_in)
        delta_cc = max(0, new_cc - seen_cc)
        delta_cr = max(0, new_cr - seen_cr)
        delta_out = max(0, new_out - seen_out)

        self._seen_per_message[key] = (
            max(seen_in, new_in),
            max(seen_cc, new_cc),
            max(seen_cr, new_cr),
            max(seen_out, new_out),
        )

        if not (delta_in or delta_cc or delta_cr or delta_out):
            return []

        delta_budget = delta_in + delta_cc + delta_out
        delta_comp_prompt = delta_in + delta_cc + delta_cr

        self.total_input_tokens += delta_in
        self.total_cache_creation_input_tokens += delta_cc
        self.total_cache_read_input_tokens += delta_cr
        self.total_output_tokens += delta_out
        self.total_budget_tokens += delta_budget
        self.total_completion_prompt_tokens += delta_comp_prompt

        return [{
            "input_tokens": delta_in,
            "cache_creation_input_tokens": delta_cc,
            "cache_read_input_tokens": delta_cr,
            "output_tokens": delta_out,
            "budget_tokens": delta_budget,
            "completion_prompt_tokens": delta_comp_prompt,
        }]

    def _observe_result_usage(self, usage: Any) -> list[dict[str, int]]:
        self._result_seen = True
        if not isinstance(usage, dict):
            # ResultMessage without valid usage cannot be certified complete
            self._accounting_complete = False
            return []

        res_in = _safe_int(usage.get("input_tokens"))
        res_cc = _safe_int(usage.get("cache_creation_input_tokens"))
        res_cr = _safe_int(usage.get("cache_read_input_tokens"))
        res_out = _safe_int(usage.get("output_tokens"))

        delta_in = max(0, res_in - self.total_input_tokens)
        delta_cc = max(0, res_cc - self.total_cache_creation_input_tokens)
        delta_cr = max(0, res_cr - self.total_cache_read_input_tokens)
        delta_out = max(0, res_out - self.total_output_tokens)

        self._accounting_complete = True

        if not (delta_in or delta_cc or delta_cr or delta_out):
            return []

        delta_budget = delta_in + delta_cc + delta_out
        delta_comp_prompt = delta_in + delta_cc + delta_cr

        self.total_input_tokens += delta_in
        self.total_cache_creation_input_tokens += delta_cc
        self.total_cache_read_input_tokens += delta_cr
        self.total_output_tokens += delta_out
        self.total_budget_tokens += delta_budget
        self.total_completion_prompt_tokens += delta_comp_prompt

        return [{
            "input_tokens": delta_in,
            "cache_creation_input_tokens": delta_cc,
            "cache_read_input_tokens": delta_cr,
            "output_tokens": delta_out,
            "budget_tokens": delta_budget,
            "completion_prompt_tokens": delta_comp_prompt,
        }]

    def is_accounting_complete(self) -> bool:
        """True only when a valid ResultMessage was observed and settled."""
        return self._result_seen and self._accounting_complete
