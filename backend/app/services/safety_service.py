"""Medical/wellbeing safety guardrails.

Every user message is screened before the coaching agent sees it:

1. Red-flag rules: regular expressions for symptoms and statements that need an immediate,
   fixed response (possible cardiac event, stroke signs, suicidal thoughts, purging, acute
   injury, performance-enhancing drugs). A match short-circuits the agent: the user gets a
   pre-written message, so emergency wording never depends on the LLM.
2. An LLM classifier for subtler cases. Its result is passed to the agent as an instruction
   (CAUTIONED/REFERRED) rather than replacing the reply.

Agent replies are checked too (e.g. no daily calorie targets below the safety floor).
Every flagged turn is stored as a `SafetyEvent`.
"""

import logging
import re
import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.agent.prompts import SAFETY_CLASSIFIER_PROMPT
from app.models import SafetyEvent, UserProfile
from app.models.enums import SafetyAction, SafetyCategory, SafetySeverity
from app.schemas import SafetyAssessment
from app.services import llm_client
from app.services.llm_client import LLMError, StructuredLLM

logger = logging.getLogger(__name__)

MIN_SAFE_DAILY_CALORIES = 1200
"""Floor below which the coach will never recommend a daily intake."""

# Actions after which the agent must not answer: the fixed template is the whole reply.
SHORT_CIRCUIT_ACTIONS = {SafetyAction.EMERGENCY, SafetyAction.BLOCKED, SafetyAction.REFERRED}

EMERGENCY_CARDIO = (
    "Please stop exercising now and rest. Chest pain or pressure, fainting, severe breathlessness, "
    "a racing irregular heartbeat, or sudden weakness, numbness or slurred speech can be signs of a "
    "medical emergency. Call your local emergency number now (for example 112 in Europe or 911 in the "
    "US), or ask someone nearby to call. Don't drive yourself. I can't safely coach you through this, "
    "so please get medical help right away."
)
EMERGENCY_MENTAL_HEALTH = (
    "I'm really sorry you're feeling this way, and I'm glad you told me. You deserve support right now. "
    "If you might act on these thoughts or you're in danger, please call your local emergency number "
    "now. You can also talk to a crisis line in your country; findahelpline.com lists free, "
    "confidential services. If you can, reach out to someone you trust and let them know how you're "
    "feeling. You don't have to go through this alone."
)
REFER_EATING = (
    "Thank you for sharing that; it takes courage. Making yourself sick, using laxatives, or starving "
    "yourself to control weight can seriously harm your health, and it can be a sign that food and "
    "your body are feeling really hard right now. I'd gently encourage you to talk to a doctor or an "
    "eating-disorder support service in your country. Meanwhile I'd rather not focus on calories or "
    "weight; if you'd like, we can focus on strength, energy and feeling good instead."
)
REFER_INJURY = (
    "Please stop that exercise and avoid anything that causes the pain. Sharp pain, a popping "
    "sensation, swelling, or not being able to put weight on a joint should be checked by a doctor "
    "or physiotherapist before you train it again. If the pain is severe, the area looks deformed, "
    "or you can't move it, seek urgent care. Once it's been assessed, I can adjust your program to "
    "work around it."
)
BLOCK_DRUGS = (
    "I can't give advice on steroids, SARMs, fat-burning drugs or other performance-enhancing "
    "substances. They carry serious health risks (heart, liver, hormones and mental health) and "
    "should only be discussed with a doctor. I'm happy to help you make great progress with "
    "training, nutrition and recovery instead."
)


class ClassifierResult(BaseModel):
    """What the LLM classifier returns (it never writes user-facing text)."""

    is_flagged: bool
    category: SafetyCategory | None
    severity: SafetySeverity | None
    recommended_action: Literal["logged", "cautioned", "referred"]
    rationale: str


@dataclass(frozen=True)
class RedFlagRule:
    category: SafetyCategory
    severity: SafetySeverity
    action: SafetyAction
    message: str
    patterns: tuple[str, ...]


RED_FLAG_RULES: tuple[RedFlagRule, ...] = (
    RedFlagRule(SafetyCategory.CARDIOVASCULAR, SafetySeverity.CRITICAL, SafetyAction.EMERGENCY, EMERGENCY_CARDIO, (
        r"\bchest\s+(?:pain|pains|pressure|tightness|is\s+(?:tight|hurting))",
        r"\b(?:pain|pressure|tightness)\s+in\s+(?:my\s+)?chest",
        r"\bchest\s+(?:feels|felt)\s+(?:tight|heavy|crushed)",
        r"\b(?:fainted|passed\s+out|blacked\s+out|lost\s+consciousness)",
        r"\b(?:about|going)\s+to\s+(?:faint|pass\s+out)",
        r"\bfeel(?:ing)?\s+(?:like\s+)?(?:i'?m\s+going\s+to\s+)?faint",
        r"\b(?:can'?t|cannot|can\s+not|struggling\s+to)\s+breathe",
        r"\bheart\s+(?:is\s+)?(?:racing|pounding|skipping|fluttering)\s+(?:and|even)\b",
        r"\birregular\s+heart\s*beat",
        r"\bslurred\s+speech",
        r"\b(?:face|mouth)\s+(?:is\s+)?(?:drooping|droops)",
        r"\bnumb(?:ness)?\s+(?:on|down)\s+one\s+side",
        r"\bworst\s+headache",
    )),
    RedFlagRule(SafetyCategory.MENTAL_HEALTH, SafetySeverity.CRITICAL, SafetyAction.EMERGENCY,
                EMERGENCY_MENTAL_HEALTH, (
        r"\bkill\s+myself",
        r"\bsuicid",
        r"\bend\s+(?:my|it)\s+(?:life|all)",
        r"\bwant\s+to\s+die\b",
        r"\b(?:self[-\s]?harm|hurt(?:ing)?\s+myself|cut(?:ting)?\s+myself)",
        r"\bno\s+reason\s+to\s+live",
    )),
    RedFlagRule(SafetyCategory.EATING_DISORDER, SafetySeverity.HIGH, SafetyAction.REFERRED, REFER_EATING, (
        r"\bmake\s+myself\s+(?:throw\s+up|vomit|sick)",
        r"\bthrow(?:ing)?\s+up\s+after\s+(?:i\s+)?eat",
        r"\bpurg(?:e|ing)\b",
        r"\blaxatives?\b",
        r"\bstarv(?:e|ing)\s+myself",
        r"\bbinge\s+and\s+(?:purge|vomit)",
    )),
    RedFlagRule(SafetyCategory.INJURY, SafetySeverity.HIGH, SafetyAction.REFERRED, REFER_INJURY, (
        r"\b(?:heard|felt)\s+(?:a\s+)?(?:pop|snap|tear)",
        r"\bsharp\s+(?:stabbing\s+)?pain",
        r"\bstabbing\s+pain",
        r"\bcan'?t\s+(?:put|bear)\s+(?:any\s+)?weight\s+on",
        r"\b(?:very|really|badly)\s+swollen",
        r"\bdislocat",
    )),
    RedFlagRule(SafetyCategory.MEDICATION, SafetySeverity.HIGH, SafetyAction.BLOCKED, BLOCK_DRUGS, (
        r"\bsteroids?\b",
        r"\bsarms?\b",
        r"\bclenbuterol\b",
        r"\bdnp\b",
        r"\b(?:tren|trenbolone|anavar|dianabol|winstrol)\b",
        r"\btestosterone\s+(?:cycle|injections?|shots?)",
    )),
)

_COMPILED = [(rule, [re.compile(p, re.IGNORECASE) for p in rule.patterns]) for rule in RED_FLAG_RULES]

_DAILY_CALORIES = re.compile(
    r"(\d{1,2}[,.]?\d{3}|\d{3,4})\s*(?:kcal|calories|cal)\s*(?:a|per|each)\s*day|"
    r"(\d{1,2}[,.]?\d{3}|\d{3,4})\s*(?:kcal|calories)\s*daily",
    re.IGNORECASE,
)


def check_red_flags(text: str) -> SafetyAssessment | None:
    """Return the most severe matching red-flag rule as an assessment, or None."""
    for rule, patterns in _COMPILED:  # rules are ordered most severe first
        for pattern in patterns:
            if match := pattern.search(text):
                return SafetyAssessment(
                    is_flagged=True, category=rule.category, severity=rule.severity,
                    recommended_action=rule.action,
                    rationale=f"Red-flag phrase matched: {match.group(0)!r}",
                    user_facing_message=rule.message,
                )
    return None


def low_calorie_recommendations(text: str) -> list[int]:
    """Daily calorie figures below the safety floor mentioned in `text`."""
    values = []
    for match in _DAILY_CALORIES.finditer(text):
        number = int(re.sub(r"[,.]", "", match.group(1) or match.group(2)))
        if number < MIN_SAFE_DAILY_CALORIES:
            values.append(number)
    return values


# --- Profile (onboarding) screening -----------------------------------------------------------

@dataclass(frozen=True)
class ProfileRule:
    category: SafetyCategory
    severity: SafetySeverity
    label: str
    patterns: tuple[str, ...]


# Conditions for which exercise guidance (PAR-Q+ style) recommends medical clearance before
# training hard. Ordered most severe first.
PROFILE_RULES: tuple[ProfileRule, ...] = (
    ProfileRule(SafetyCategory.CARDIOVASCULAR, SafetySeverity.HIGH, "a heart condition", (
        r"\bheart\s+(?:disease|failure|condition|problems?|attack|surgery|valve)",
        r"\bcardi(?:ac|omyopathy)", r"\barrh?ythmi", r"\batrial\s+fibrillation", r"\bafib\b",
        r"\bangina\b", r"\bpacemaker", r"\bbypass\s+surgery", r"\bstents?\b",
    )),
    ProfileRule(SafetyCategory.CARDIOVASCULAR, SafetySeverity.HIGH, "a stroke", (r"\bstroke\b", r"\btia\b")),
    ProfileRule(SafetyCategory.CARDIOVASCULAR, SafetySeverity.HIGH, "uncontrolled blood pressure", (
        r"\b(?:uncontrolled|very\s+high|severe)\s+(?:blood\s+pressure|hypertension)",
    )),
    ProfileRule(SafetyCategory.EATING_DISORDER, SafetySeverity.HIGH, "an eating disorder", (
        r"\banorexi", r"\bbulimi", r"\beating\s+disorder", r"\bbinge[-\s]eating",
    )),
    ProfileRule(SafetyCategory.MEDICAL_CONDITION, SafetySeverity.HIGH, "kidney disease", (
        r"\bkidney\s+(?:disease|failure)", r"\brenal\s+failure", r"\bdialysis",
    )),
    ProfileRule(SafetyCategory.MEDICAL_CONDITION, SafetySeverity.MEDIUM, "recent surgery", (
        r"\brecent(?:ly)?\s+(?:had\s+)?(?:an?\s+)?(?:surgery|operation)", r"\bpost[-\s]?op\b",
        r"\b(?:surgery|operation)\s+(?:last|this)\s+(?:week|month)",
    )),
    ProfileRule(SafetyCategory.PREGNANCY, SafetySeverity.MEDIUM, "pregnancy", (r"\bpregnan",)),
    ProfileRule(SafetyCategory.MEDICAL_CONDITION, SafetySeverity.MEDIUM, "insulin-treated diabetes", (
        r"\binsulin\b", r"\btype\s*1\s+diabetes", r"\bt1d\b",
    )),
    ProfileRule(SafetyCategory.MEDICAL_CONDITION, SafetySeverity.MEDIUM, "epilepsy or seizures", (
        r"\bepilep", r"\bseizures?\b",
    )),
)
_PROFILE_COMPILED = [(rule, [re.compile(p, re.IGNORECASE) for p in rule.patterns]) for rule in PROFILE_RULES]

CLEARANCE_SEVERITIES = {SafetySeverity.MEDIUM, SafetySeverity.HIGH, SafetySeverity.CRITICAL}


def screen_profile_text(injuries: str | None, medical_conditions: str | None,
                        medical_clearance: bool = False) -> SafetyAssessment:
    """Deterministic screen of the health answers given at onboarding (no LLM).

    Current red-flag symptoms (e.g. chest pain, fainting) are CRITICAL; conditions that call for
    medical clearance are HIGH or MEDIUM. Unflagged text returns `is_flagged=False`. When the
    user has confirmed doctor clearance, the assessment is LOGGED rather than acted on.
    """
    text = " ".join(filter(None, [injuries, medical_conditions]))
    if not text.strip():
        return SafetyAssessment(is_flagged=False)

    if (symptom := check_red_flags(text)) is not None and symptom.severity == SafetySeverity.CRITICAL:
        message = ("Your profile mentions symptoms such as chest pain, fainting or breathing problems. "
                   "Please see a doctor before training. Until you confirm a doctor has cleared you "
                   "for exercise, Coachin won't generate a training program.")
        assessment = symptom.model_copy(update={"recommended_action": SafetyAction.BLOCKED,
                                                "user_facing_message": message})
    else:
        match = next(((rule, m) for rule, patterns in _PROFILE_COMPILED for p in patterns
                      if (m := p.search(text))), None)
        if match is None:
            return SafetyAssessment(is_flagged=False)
        rule, found = match
        message = (f"You mentioned {rule.label}. Please check with your doctor before training hard. "
                   "Until you confirm a doctor has cleared you for exercise, Coachin keeps your "
                   "program at a moderate effort (RPE 7 or below)"
                   + (" and won't suggest a calorie deficit" if rule.category == SafetyCategory.EATING_DISORDER
                      else "") + ".")
        assessment = SafetyAssessment(
            is_flagged=True, category=rule.category, severity=rule.severity,
            recommended_action=SafetyAction.REFERRED,
            rationale=f"Profile mentions {rule.label}: {found.group(0)!r}", user_facing_message=message,
        )
    if medical_clearance:
        return assessment.model_copy(update={
            "recommended_action": SafetyAction.LOGGED,
            "user_facing_message": "Noted: you've confirmed a doctor has cleared you for exercise. "
                                   "Stop and seek help if you notice any warning symptoms.",
        })
    return assessment


def needs_clearance(profile: UserProfile | None) -> bool:
    """True when the profile's health answers call for clearance the user hasn't confirmed."""
    if profile is None or profile.medical_clearance:
        return False
    screen = screen_profile_text(profile.injuries, profile.medical_conditions)
    return screen.is_flagged and screen.severity in CLEARANCE_SEVERITIES


def blocks_program_generation(profile: UserProfile | None) -> bool:
    """Current red-flag symptoms without confirmed clearance block program generation."""
    if profile is None or profile.medical_clearance:
        return False
    return screen_profile_text(profile.injuries, profile.medical_conditions).severity == SafetySeverity.CRITICAL


def has_eating_disorder_history(profile: UserProfile | None) -> bool:
    if profile is None:
        return False
    screen = screen_profile_text(profile.injuries, profile.medical_conditions)
    return screen.is_flagged and screen.category == SafetyCategory.EATING_DISORDER


class SafetyService:
    def __init__(self, db: Session, llm: StructuredLLM | None = None) -> None:
        self.db = db
        self.llm = llm or llm_client.complete_structured

    def screen_input(self, text: str, profile: UserProfile | None) -> SafetyAssessment:
        """Classify a user message: red-flag rules first, then the LLM classifier.

        If the classifier call fails, the message is treated as unflagged (the red-flag rules
        still cover the critical cases) and a warning is logged.
        """
        if flagged := check_red_flags(text):
            return flagged
        context = ""
        if profile is not None:
            context = (f"User-reported injuries: {profile.injuries or 'none'}; "
                       f"medical conditions: {profile.medical_conditions or 'none'}; "
                       f"doctor clearance: {'yes' if profile.medical_clearance else 'no'}.")
        messages = [{"role": "user", "content": SAFETY_CLASSIFIER_PROMPT.format(
            categories=", ".join(c.value for c in SafetyCategory),
            severities=", ".join(s.value for s in SafetySeverity),
            actions="logged, cautioned, referred",
            context=context or "none",
            text=text,
        )}]
        try:
            result = self.llm(messages, ClassifierResult)
        except LLMError as exc:
            logger.warning("Safety classifier failed; relying on red-flag rules only: %s", exc)
            return SafetyAssessment(is_flagged=False)
        if not result.is_flagged:
            return SafetyAssessment(is_flagged=False)
        # The classifier never short-circuits the agent on its own ("referred" becomes a strong
        # caution); it guides the reply instead.
        return SafetyAssessment(
            is_flagged=True,
            category=result.category or SafetyCategory.OTHER,
            severity=result.severity or SafetySeverity.LOW,
            recommended_action=SafetyAction.LOGGED if result.recommended_action == "logged" else SafetyAction.CAUTIONED,
            rationale=result.rationale,
        )

    def screen_profile(self, profile: UserProfile) -> SafetyAssessment:
        """Evaluate the injuries/medical conditions given at onboarding (rules only, no LLM)."""
        return self.screen_profile_static(profile)

    @staticmethod
    def screen_profile_static(profile: UserProfile) -> SafetyAssessment:
        return screen_profile_text(profile.injuries, profile.medical_conditions, profile.medical_clearance)

    def screen_output(self, text: str) -> SafetyAssessment:
        """Check an agent reply for unsafe advice before it reaches the user."""
        if too_low := low_calorie_recommendations(text):
            return SafetyAssessment(
                is_flagged=True, category=SafetyCategory.EXTREME_DIETING, severity=SafetySeverity.HIGH,
                recommended_action=SafetyAction.BLOCKED,
                rationale=f"Reply suggested {too_low[0]} kcal/day, below the {MIN_SAFE_DAILY_CALORIES} kcal floor.",
                user_facing_message=(
                    f"I can't recommend eating fewer than {MIN_SAFE_DAILY_CALORIES:,} calories a day without "
                    "medical supervision. Very low intakes cause muscle loss, fatigue and nutrient "
                    "deficiencies. A moderate deficit (about 0.5-1% of body weight per week) works better "
                    "and lasts. Check the Nutrition page for targets based on your profile."
                ),
            )
        return SafetyAssessment(is_flagged=False)

    def record_event(
        self,
        user_id: uuid.UUID,
        assessment: SafetyAssessment,
        trigger_text: str,
        message_id: uuid.UUID | None = None,
    ) -> SafetyEvent:
        """Persist a flagged assessment as a `SafetyEvent` (caller commits)."""
        event = SafetyEvent(
            user_id=user_id,
            message_id=message_id,
            category=assessment.category or SafetyCategory.OTHER,
            severity=assessment.severity or SafetySeverity.LOW,
            action_taken=assessment.recommended_action,
            trigger_text=trigger_text[:4000],
            rationale=assessment.rationale,
        )
        self.db.add(event)
        return event
