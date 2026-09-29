"""The coaching agent's reasoning loop: context + retrieval + tool calls."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.agent.prompts import COACH_SYSTEM_PROMPT, NO_REFERENCE_MATERIAL
from app.agent.tools import ACTION_LABELS, TOOL_DEFINITIONS, TOOL_HANDLERS, ToolContext, ToolError
from app.models import Message, User
from app.models.enums import MessageRole
from app.rag.retriever import KnowledgeRetriever
from app.services import llm_client
from app.services.llm_client import LLMError, LLMReply, ToolLLM
from app.services.nutrition_service import NutritionService
from app.services.program_service import ProgramService, describe_profile

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 5
HISTORY_MESSAGES = 12
FALLBACK_REPLY = "Sorry, I got a bit tangled up there. Could you say that again?"


@dataclass
class AgentResult:
    """Outcome of one agent turn."""

    reply: str
    actions: list[str] = field(default_factory=list)
    """Labels of data-changing tools that succeeded (e.g. "logged_meal")."""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    """Audit log of every tool call with its arguments and result."""
    retrieved_sources: list[str] = field(default_factory=list)


class CoachAgent:
    """Tool-calling LLM agent that answers, coaches, and records data for the user."""

    def __init__(
        self,
        db: Session,
        llm: ToolLLM | None = None,
        retriever: KnowledgeRetriever | None = None,
        nutrition: NutritionService | None = None,
    ) -> None:
        self.db = db
        self.llm = llm or llm_client.chat_with_tools
        self.retriever = retriever or KnowledgeRetriever()
        self.nutrition = nutrition or NutritionService(db, retriever=self.retriever)

    def build_user_context(self, user: User, tz_name: str) -> str:
        """Summarize profile, active program, today's workout and nutrition for the prompt."""
        lines = [f"Name: {user.full_name or 'not given'}"]
        now = datetime.now(ZoneInfo(tz_name))
        if user.profile is None:
            lines.append("The user hasn't completed their profile yet; suggest doing so on the Profile page.")
            return "\n".join(lines)
        lines.append(describe_profile(user.profile, now.date()))
        lines.append(f"Goal: {user.profile.primary_goal}; trains {user.profile.training_days_per_week} days/week.")

        program = ProgramService(self.db).get_active(user.id)
        if program is None:
            lines.append("Active program: none.")
        else:
            week = ProgramService.current_week_number(program, now.date())
            today = next((w for w in program.workouts
                          if w.week_number == week and w.day_of_week == now.weekday()), None)
            lines.append(f"Active program: {program.name}, week {week} of {program.duration_weeks}. "
                         f"Today: {today.name if today else 'rest day'}.")

        day = self.nutrition.daily_summary(user.id, user.profile, now.date(), tz_name)
        eaten = f"{day.totals.calories:.0f} kcal, {day.totals.protein_g:.0f} g protein"
        target = (f" of {day.targets.calories:.0f} kcal, {day.targets.protein_g:.0f} g protein"
                  if day.targets else "")
        lines.append(f"Eaten today: {eaten}{target}.")
        return "\n".join(lines)

    def run(
        self,
        user: User,
        user_message: str,
        history: list[Message],
        tz_name: str = "UTC",
        safety_instruction: str | None = None,
    ) -> AgentResult:
        """Execute one turn.

        Retrieves relevant knowledge, builds the system prompt, then loops: call the LLM with
        `TOOL_DEFINITIONS`, execute any requested tools via `TOOL_HANDLERS`, feed results back,
        until a final text reply or `MAX_TOOL_ITERATIONS` is reached.

        Raises:
            LLMError: the model could not be reached.
        """
        docs = self.retriever.retrieve(user_message)
        now = datetime.now(ZoneInfo(tz_name))
        system = COACH_SYSTEM_PROMPT.format(
            safety_instruction=f"\nSafety note for this message: {safety_instruction}\n" if safety_instruction else "",
            now=now.strftime("%A %d %B %Y, %H:%M"),
            user_context=self.build_user_context(user, tz_name),
            retrieved_context=KnowledgeRetriever.format_context(docs) or NO_REFERENCE_MATERIAL,
        )
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for past in history[-HISTORY_MESSAGES:]:
            if past.role in (MessageRole.USER, MessageRole.ASSISTANT):
                messages.append({"role": str(past.role), "content": past.content})
        messages.append({"role": "user", "content": user_message})

        result = AgentResult(reply="", retrieved_sources=KnowledgeRetriever.source_ids(docs))
        ctx = ToolContext(db=self.db, user=user, tz_name=tz_name, nutrition=self.nutrition)

        for _ in range(MAX_TOOL_ITERATIONS):
            reply: LLMReply = self.llm(messages, TOOL_DEFINITIONS)
            if not reply.tool_calls:
                result.reply = (reply.content or "").strip() or FALLBACK_REPLY
                return result
            messages.append({
                "role": "assistant", "content": reply.content,
                "tool_calls": [{"id": c.id, "type": "function",
                                "function": {"name": c.name, "arguments": c.arguments}} for c in reply.tool_calls],
            })
            for call in reply.tool_calls:
                output = self._execute(ctx, call.name, call.arguments)
                result.tool_calls.append({"name": call.name, "arguments": call.arguments, "result": output})
                if "error" not in output and call.name in ACTION_LABELS:
                    result.actions.append(ACTION_LABELS[call.name])
                messages.append({"role": "tool", "tool_call_id": call.id,
                                 "content": json.dumps(output, default=str)})

        logger.warning("Agent hit MAX_TOOL_ITERATIONS for user %s", user.id)
        result.reply = FALLBACK_REPLY
        return result

    def _execute(self, ctx: ToolContext, name: str, raw_arguments: str) -> dict[str, Any]:
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return {"error": f"Unknown tool {name!r}."}
        try:
            arguments = json.loads(raw_arguments or "{}")
            if not isinstance(arguments, dict):
                raise ValueError("arguments must be an object")
        except ValueError:
            return {"error": "Tool arguments were not valid JSON."}
        try:
            return handler(ctx, arguments)
        except ToolError as exc:
            self.db.rollback()
            return {"error": str(exc)}
        except LLMError:
            raise
        except Exception:  # never let a tool bug crash the conversation
            self.db.rollback()
            logger.exception("Tool %s failed", name)
            return {"error": "That action failed unexpectedly; nothing was saved."}
