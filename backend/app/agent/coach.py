"""The coaching agent's reasoning loop."""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.agent.prompts import COACH_SYSTEM_PROMPT  # noqa: F401
from app.agent.tools import TOOL_DEFINITIONS, TOOL_HANDLERS  # noqa: F401
from app.models import Message, User
from app.rag.retriever import KnowledgeRetriever

MAX_TOOL_ITERATIONS = 5


@dataclass
class AgentResult:
    """Outcome of one agent turn."""

    reply: str
    actions: list[str] = field(default_factory=list)
    """Names of tools that were executed."""
    tool_calls: list[dict] = field(default_factory=list)
    retrieved_sources: list[str] = field(default_factory=list)


class CoachAgent:
    """Tool-calling LLM agent that answers, coaches, and records data for the user."""

    def __init__(self, db: Session, retriever: KnowledgeRetriever | None = None) -> None:
        self.db = db
        self.retriever = retriever or KnowledgeRetriever()

    def build_user_context(self, user: User) -> str:
        """Summarize profile, active program, recent sessions, and today's nutrition for the prompt."""
        raise NotImplementedError

    def run(self, user: User, user_message: str, history: list[Message]) -> AgentResult:
        """Execute one turn.

        Retrieves relevant knowledge, builds the system prompt, then loops: call the LLM with
        `TOOL_DEFINITIONS`, execute any requested tools via `TOOL_HANDLERS`, feed results back,
        until a final text reply or `MAX_TOOL_ITERATIONS` is reached.
        """
        raise NotImplementedError
