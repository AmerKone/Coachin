"""Tools the coaching agent can call (OpenAI function-calling format) and their handlers."""

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.models import User

ToolHandler = Callable[[Session, User, dict[str, Any]], dict[str, Any]]


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_todays_workout",
            "description": "Return today's planned workout with progressive-overload targets.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_workout_set",
            "description": "Log a performed set for an exercise in today's session.",
            "parameters": {
                "type": "object",
                "properties": {
                    "exercise_name": {"type": "string"},
                    "reps": {"type": "integer"},
                    "weight_kg": {"type": "number"},
                    "rpe": {"type": "number"},
                },
                "required": ["exercise_name", "reps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_meal",
            "description": "Estimate macros for a described meal and log it.",
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "meal_type": {"type": "string", "enum": ["breakfast", "lunch", "dinner", "snack"]},
                },
                "required": ["description"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_nutrition_summary",
            "description": "Return today's calorie and macro totals versus targets.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_body_weight",
            "description": "Record the user's body weight.",
            "parameters": {
                "type": "object",
                "properties": {"weight_kg": {"type": "number"}},
                "required": ["weight_kg"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "swap_exercise",
            "description": "Replace an exercise in the active program (e.g. due to equipment or discomfort).",
            "parameters": {
                "type": "object",
                "properties": {
                    "current_exercise": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["current_exercise", "reason"],
            },
        },
    },
]


def get_todays_workout(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError


def log_workout_set(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError


def log_meal(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError


def get_nutrition_summary(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError


def log_body_weight(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError


def swap_exercise(db: Session, user: User, args: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError


TOOL_HANDLERS: dict[str, ToolHandler] = {
    "get_todays_workout": get_todays_workout,
    "log_workout_set": log_workout_set,
    "log_meal": log_meal,
    "get_nutrition_summary": get_nutrition_summary,
    "log_body_weight": log_body_weight,
    "swap_exercise": swap_exercise,
}
