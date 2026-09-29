"""Tests for safety guardrails, coach tools, the agent loop, chat and voice (all LLM/audio faked)."""

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agent.coach import FALLBACK_REPLY, MAX_TOOL_ITERATIONS, CoachAgent
from app.agent.tools import ToolContext, ToolError, get_todays_workout, log_body_weight, log_workout_set, swap_exercise
from app.api.routes.chat import get_chat_service
from app.api.routes.voice import get_voice_service
from app.main import app
from app.models import (
    Conversation,
    Exercise,
    ExerciseSet,
    Message,
    PlannedExercise,
    ProgramWorkout,
    SafetyEvent,
    TrainingProgram,
    User,
    WorkoutSession,
)
from app.models.enums import ProgramStatus, SafetyAction, SafetyCategory
from app.rag.retriever import KnowledgeRetriever
from app.schemas import ExerciseCreate, TranscriptionResponse
from app.services.chat_service import ChatService
from app.services.exercise_service import upsert_exercises
from app.services.llm_client import LLMError, LLMReply, ToolCall
from app.services.nutrition_service import NutritionService
from app.services.safety_service import SafetyService, check_red_flags, low_calorie_recommendations
from app.services.voice_service import VoiceError, VoiceService, _chunks
from tests.conftest import clear_exercise_library

CHAT = "/api/v1/chat"
VOICE = "/api/v1/voice"

# --- Fakes ----------------------------------------------------------------


def say(text: str) -> LLMReply:
    return LLMReply(content=text)


def call(name: str, **arguments) -> LLMReply:
    return LLMReply(content=None, tool_calls=[ToolCall(id=f"call_{name}", name=name, arguments=json.dumps(arguments))])


class FakeToolLLM:
    def __init__(self, *replies: LLMReply | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[list[dict[str, Any]]] = []

    def __call__(self, messages, tools):
        self.calls.append([dict(m) for m in messages])
        reply = self.replies.pop(0) if self.replies else say("(no more scripted replies)")
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeStructured:
    """Stands in for `complete_structured` (safety classifier / meal estimator)."""

    def __init__(self, *responses: dict[str, Any] | Exception) -> None:
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, messages, schema):
        self.calls += 1
        response = self.responses.pop(0) if self.responses else {
            "is_flagged": False, "category": None, "severity": None, "recommended_action": "logged",
            "rationale": "ordinary fitness chat"}
        if isinstance(response, Exception):
            raise response
        return schema.model_validate(response)


class NoKnowledge:
    def similarity_search_with_score(self, query, k=4, filter=None):
        return []


class FakeVoice:
    def __init__(self, transcript: str = "") -> None:
        self.transcript = transcript
        self.spoken: list[str] = []

    def transcribe(self, audio: bytes, filename: str) -> TranscriptionResponse:
        return TranscriptionResponse(text=self.transcript)

    def synthesize(self, text: str, voice: str | None = None) -> bytes:
        self.spoken.append(text)
        return b"ID3-fake-mp3"


MEAL = {"meal_type": "lunch", "assumptions": "", "items": [
    {"food": "Chicken wrap", "portion": "1 wrap", "calories": 450, "protein_g": 30, "carbs_g": 45, "fat_g": 15}]}


@pytest.fixture
def fakes(db: Session):
    """Wire ChatService with fakes; returns them so tests can script replies."""
    retriever = KnowledgeRetriever(store=NoKnowledge())
    state = {"agent_llm": FakeToolLLM(), "classifier": FakeStructured(), "meal_llm": FakeStructured(MEAL),
             "voice": FakeVoice()}

    def service() -> ChatService:
        nutrition = NutritionService(db, llm=state["meal_llm"], retriever=retriever)
        agent = CoachAgent(db, llm=state["agent_llm"], retriever=retriever, nutrition=nutrition)
        return ChatService(db, agent=agent, safety=SafetyService(db, llm=state["classifier"]), voice=state["voice"])

    app.dependency_overrides[get_chat_service] = service
    app.dependency_overrides[get_voice_service] = lambda: state["voice"]
    yield state
    app.dependency_overrides.pop(get_chat_service, None)
    app.dependency_overrides.pop(get_voice_service, None)


@pytest.fixture
def library(db: Session) -> dict[str, uuid.UUID]:
    clear_exercise_library(db)
    upsert_exercises(db, [
        ExerciseCreate(name="Barbell Back Squat", primary_muscle="quadriceps", category="compound",
                       equipment=["barbell", "squat rack"]),
        ExerciseCreate(name="Goblet Squat", primary_muscle="quadriceps", category="compound", equipment=["dumbbells"]),
        ExerciseCreate(name="Leg Press", primary_muscle="quadriceps", category="compound", equipment=["machines"]),
        ExerciseCreate(name="Push-Up", primary_muscle="chest", category="compound", is_bodyweight=True),
    ])
    return {e.name: e.id for e in db.scalars(select(Exercise))}


@pytest.fixture
def user(client: TestClient, auth_headers, db: Session) -> User:
    client.put("/api/v1/users/me/profile", headers=auth_headers, json={
        "sex": "female", "date_of_birth": "1995-01-01", "height_cm": 168, "weight_kg": 64,
        "available_equipment": ["barbell", "squat rack", "dumbbells"]})
    return db.scalar(select(User).where(User.email == "alex@example.com"))


@pytest.fixture
def program(db: Session, user: User, library) -> TrainingProgram:
    """Active 1-week program starting this Monday with a squat workout every day."""
    today = date.today()
    program = TrainingProgram(user_id=user.id, name="Squat Block", goal="strength", status=ProgramStatus.ACTIVE,
                              start_date=today - timedelta(days=today.weekday()), duration_weeks=1)
    program.workouts = [ProgramWorkout(week_number=1, day_of_week=d, name=f"Legs {d}", exercises=[
        PlannedExercise(exercise_id=library["Barbell Back Squat"], position=1, target_sets=3,
                        target_reps_min=5, target_reps_max=8, target_rpe=8)]) for d in range(7)]
    db.add(program)
    db.commit()
    return program


def ctx(db: Session, user: User) -> ToolContext:
    return ToolContext(db=db, user=user, tz_name="UTC", nutrition=NutritionService(
        db, llm=FakeStructured(MEAL), retriever=KnowledgeRetriever(store=NoKnowledge())))


# --- Safety rules ---------------------------------------------------------


@pytest.mark.parametrize(("text", "category"), [
    ("I get chest pain when I run", SafetyCategory.CARDIOVASCULAR),
    ("I passed out after my last set", SafetyCategory.CARDIOVASCULAR),
    ("sometimes I want to die", SafetyCategory.MENTAL_HEALTH),
    ("I make myself throw up after dinner", SafetyCategory.EATING_DISORDER),
    ("I felt a pop in my knee", SafetyCategory.INJURY),
    ("should I run a steroid cycle?", SafetyCategory.MEDICATION),
])
def test_red_flags_detected(text: str, category: SafetyCategory) -> None:
    assessment = check_red_flags(text)
    assert assessment is not None and assessment.category == category
    assert assessment.user_facing_message


@pytest.mark.parametrize("text", [
    "Today is chest day!", "How many sets of chest press?", "I'm dying to try deadlifts",
    "starving after my workout, what should I eat?", "my legs are sore, is that normal?", "is creatine safe?",
])
def test_ordinary_fitness_chat_is_not_flagged(text: str) -> None:
    assert check_red_flags(text) is None


def test_low_calorie_detection() -> None:
    assert low_calorie_recommendations("Aim for 1,000 calories a day") == [1000]
    assert low_calorie_recommendations("Your target is 1,700 kcal per day; lunch was 400 kcal") == []


def test_classifier_is_advisory_and_fails_open(db: Session) -> None:
    referred = {"is_flagged": True, "category": "injury", "severity": "medium",
                "recommended_action": "referred", "rationale": "ongoing knee ache"}
    safety = SafetyService(db, llm=FakeStructured(referred, LLMError("down")))
    assessment = safety.screen_input("my knee has ached for a week", None)
    assert assessment.is_flagged and assessment.recommended_action == SafetyAction.CAUTIONED  # never short-circuits
    assert assessment.user_facing_message is None
    assert safety.screen_input("my knee has ached for a week", None).is_flagged is False  # classifier down


# --- Tools ----------------------------------------------------------------


def test_log_workout_set_builds_todays_session(db: Session, user: User, program: TrainingProgram) -> None:
    c = ctx(db, user)
    first = log_workout_set(c, {"exercise_name": "barbell back squat", "reps": 8, "weight_kg": 80, "rpe": 7})
    second = log_workout_set(c, {"exercise_name": "Back Squat", "reps": 7, "weight_kg": 80})
    assert (first["logged"]["set_number"], second["logged"]["set_number"]) == (1, 2)

    session = db.scalar(select(WorkoutSession).where(WorkoutSession.user_id == user.id))
    assert session.program_workout_id is not None  # linked to today's planned workout
    assert db.scalar(select(func.count()).select_from(ExerciseSet).where(ExerciseSet.session_id == session.id)) == 2

    with pytest.raises(ToolError, match="Did you mean"):
        log_workout_set(c, {"exercise_name": "squat", "reps": 5})  # ambiguous
    with pytest.raises(ToolError):
        log_workout_set(c, {"exercise_name": "Push-Up", "reps": 0})


def test_get_todays_workout(db: Session, user: User, program: TrainingProgram, library) -> None:
    result = get_todays_workout(ctx(db, user), {})
    assert result["status"] == "training_day"
    assert result["workout"]["exercises"][0]["exercise"] == "Barbell Back Squat"


def test_log_body_weight_updates_profile(db: Session, user: User) -> None:
    result = log_body_weight(ctx(db, user), {"weight_kg": 63.2})
    assert result == {"logged_weight_kg": 63.2, "previous_profile_weight_kg": 64}
    assert user.profile.weight_kg == 63.2
    with pytest.raises(ToolError):
        log_body_weight(ctx(db, user), {"weight_kg": 5})


def test_swap_exercise_checks_equipment(db: Session, user: User, program: TrainingProgram, library) -> None:
    c = ctx(db, user)
    with pytest.raises(ToolError, match="machines"):
        swap_exercise(c, {"current_exercise": "Barbell Back Squat", "replacement_exercise": "Leg Press",
                          "reason": "knee"})
    result = swap_exercise(c, {"current_exercise": "Barbell Back Squat", "replacement_exercise": "Goblet Squat",
                               "reason": "back feels tight"})
    assert result["planned_exercises_updated"] == 7
    planned = db.scalars(select(PlannedExercise)).all()
    assert {p.exercise_id for p in planned} == {library["Goblet Squat"]}


# --- Agent loop -----------------------------------------------------------


def test_agent_runs_tools_and_reports_actions(db: Session, user: User) -> None:
    llm = FakeToolLLM(call("log_meal", description="a chicken wrap"), say("Logged your wrap: about 450 calories."))
    nutrition = NutritionService(db, llm=FakeStructured(MEAL), retriever=KnowledgeRetriever(store=NoKnowledge()))
    agent = CoachAgent(db, llm=llm, retriever=KnowledgeRetriever(store=NoKnowledge()), nutrition=nutrition)

    result = agent.run(user, "I just had a chicken wrap", history=[])
    assert result.reply == "Logged your wrap: about 450 calories."
    assert result.actions == ["logged_meal"]
    tool_message = llm.calls[1][-1]
    assert tool_message["role"] == "tool" and json.loads(tool_message["content"])["logged"]["calories"] == 450
    system = llm.calls[0][0]["content"]
    assert "Eaten today: 0 kcal" in system and "Height: 168 cm" in system


def test_agent_handles_bad_tool_calls_and_loops(db: Session, user: User) -> None:
    bad = LLMReply(content=None, tool_calls=[ToolCall(id="1", name="launch_rocket", arguments="{}"),
                                             ToolCall(id="2", name="log_body_weight", arguments="not json")])
    llm = FakeToolLLM(bad, say("Sorry, which weight?"))
    agent = CoachAgent(db, llm=llm, retriever=KnowledgeRetriever(store=NoKnowledge()))
    result = agent.run(user, "log it", history=[])
    assert [c["result"]["error"] for c in result.tool_calls] == ["Unknown tool 'launch_rocket'.",
                                                                  "Tool arguments were not valid JSON."]
    assert result.actions == [] and result.reply == "Sorry, which weight?"

    looping = FakeToolLLM(*[call("get_nutrition_summary")] * MAX_TOOL_ITERATIONS)
    assert CoachAgent(db, llm=looping, retriever=KnowledgeRetriever(store=NoKnowledge())).run(
        user, "hi", []).reply == FALLBACK_REPLY


# --- Chat endpoint --------------------------------------------------------


def test_chat_turn_persists_conversation(client: TestClient, auth_headers, user, fakes) -> None:
    fakes["agent_llm"].replies = [call("log_body_weight", weight_kg=63.5), say("Got it, 63.5 kg logged."),
                                  say("You're doing great.")]
    first = client.post(CHAT, headers=auth_headers, json={"message": "I weigh 63.5 kg today"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["assistant_message"]["content"] == "Got it, 63.5 kg logged."
    assert body["actions"] == ["logged_weight"] and body["safety_notice"] is None

    second = client.post(CHAT, headers=auth_headers, json={"message": "thanks!",
                                                           "conversation_id": body["conversation_id"]})
    assert second.json()["conversation_id"] == body["conversation_id"]
    history_sent = fakes["agent_llm"].calls[-1]
    assert [m["content"] for m in history_sent if m["role"] in ("user", "assistant")][-3:] == [
        "I weigh 63.5 kg today", "Got it, 63.5 kg logged.", "thanks!"]

    conversation = client.get(f"{CHAT}/conversations/{body['conversation_id']}", headers=auth_headers).json()
    assert [m["role"] for m in conversation["messages"]] == ["user", "assistant", "user", "assistant"]
    assert client.get(f"{CHAT}/conversations", headers=auth_headers).json()[0]["title"] == "I weigh 63.5 kg today"


def test_emergency_short_circuits_agent(client: TestClient, auth_headers, user, fakes, db: Session) -> None:
    response = client.post(CHAT, headers=auth_headers, json={"message": "I have chest pain during my sets"})
    body = response.json()
    assert fakes["agent_llm"].calls == [] and fakes["classifier"].calls == 0  # rules alone decided
    assert body["safety_notice"]["action_taken"] == "emergency"
    assert "emergency number" in body["assistant_message"]["content"]
    assert body["user_message"]["safety_flagged"] is True
    event = db.scalar(select(SafetyEvent))
    assert event.category == SafetyCategory.CARDIOVASCULAR and "chest pain" in event.trigger_text
    events = client.get("/api/v1/safety/events", headers=auth_headers).json()
    assert events[0]["action_taken"] == "emergency"


def test_cautioned_message_reaches_agent_with_instruction(client: TestClient, auth_headers, user, fakes) -> None:
    fakes["classifier"].responses = [{"is_flagged": True, "category": "injury", "severity": "low",
                                      "recommended_action": "cautioned", "rationale": "mild wrist ache"}]
    fakes["agent_llm"].replies = [say("Let's use push-up handles to keep your wrist neutral.")]
    body = client.post(CHAT, headers=auth_headers, json={"message": "my wrist aches a bit on push-ups"}).json()
    assert "Safety note for this message" in fakes["agent_llm"].calls[0][0]["content"]
    assert body["safety_notice"]["action_taken"] == "cautioned"
    assert body["assistant_message"]["content"].startswith("Let's use push-up handles")


def test_unsafe_reply_is_replaced(client: TestClient, auth_headers, user, fakes) -> None:
    fakes["agent_llm"].replies = [say("To drop weight fast, eat 900 calories a day.")]
    body = client.post(CHAT, headers=auth_headers, json={"message": "how do I lose weight fast?"}).json()
    assert "900" not in body["assistant_message"]["content"]
    assert "1,200 calories" in body["assistant_message"]["content"]
    assert body["safety_notice"]["category"] == "extreme_dieting"


def test_llm_outage_keeps_user_message(client: TestClient, auth_headers, user, fakes, db: Session) -> None:
    fakes["agent_llm"].replies = [LLMError("timeout")]
    response = client.post(CHAT, headers=auth_headers, json={"message": "what's my workout?"})
    assert response.status_code == 502
    kept = db.scalars(select(Message).join(Conversation).where(Conversation.user_id == user.id)).all()
    assert [m.content for m in kept] == ["what's my workout?"]


def test_chat_validation_and_privacy(client: TestClient, auth_headers, user, fakes) -> None:
    assert client.post(CHAT, headers=auth_headers, json={"message": "hi", "timezone": "Mars/Base"}).status_code == 422
    assert client.post(CHAT, headers=auth_headers,
                       json={"message": "hi", "conversation_id": str(uuid.uuid4())}).status_code == 404
    fakes["agent_llm"].replies = [say("Hello!")]
    conversation_id = client.post(CHAT, headers=auth_headers, json={"message": "hi"}).json()["conversation_id"]

    client.post("/api/v1/auth/register", json={"email": "other@example.com", "password": "other-password"})
    token = client.post("/api/v1/auth/login", data={"username": "other@example.com",
                                                     "password": "other-password"}).json()["access_token"]
    other = {"Authorization": f"Bearer {token}"}
    assert client.get(f"{CHAT}/conversations/{conversation_id}", headers=other).status_code == 404
    assert client.post(CHAT, headers=other, json={"message": "hi", "conversation_id": conversation_id}).status_code == 404
    assert client.delete(f"{CHAT}/conversations/{conversation_id}", headers=auth_headers).status_code == 204


# --- Voice ----------------------------------------------------------------


def test_voice_chat_transcribes_and_speaks(client: TestClient, auth_headers, user, fakes) -> None:
    fakes["voice"].transcript = "what should I train today?"
    fakes["agent_llm"].replies = [say("It's leg day: three sets of squats.")]
    response = client.post(f"{VOICE}/chat", headers=auth_headers,
                           files={"audio": ("clip.wav", b"RIFF....WAVE", "audio/wav")},
                           data={"timezone": "Africa/Algiers"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["transcript"] == "what should I train today?"
    assert body["user_message"]["is_voice"] is True
    assert body["audio_base64"] and fakes["voice"].spoken == ["It's leg day: three sets of squats."]


def test_voice_chat_rejects_silence(client: TestClient, auth_headers, user, fakes) -> None:
    fakes["voice"].transcript = ""
    response = client.post(f"{VOICE}/chat", headers=auth_headers, files={"audio": ("clip.wav", b"....", "audio/wav")})
    assert response.status_code == 422 and "didn't catch" in response.json()["detail"]


def test_speak_returns_mp3(client: TestClient, auth_headers, user, fakes) -> None:
    response = client.post(f"{VOICE}/speak", headers=auth_headers, json={"text": "Nice work!"})
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg" and response.content == b"ID3-fake-mp3"


def test_voice_service_validates_before_calling_api() -> None:
    with pytest.raises(VoiceError, match="Unsupported audio format"):
        VoiceService().transcribe(b"data", "notes.txt")
    with pytest.raises(VoiceError, match="empty"):
        VoiceService().transcribe(b"", "clip.wav")
    long_text = "This is a sentence. " * 400  # ~8000 chars
    pieces = _chunks(long_text, limit=4096)
    assert len(pieces) == 2 and all(len(p) <= 4096 for p in pieces) and pieces[0].endswith(".")
