"""Guardrails: input validation, prompt injection detection, output sanitisation."""

import re
import logging
from dataclasses import dataclass
from typing import Tuple

from edubot.config.settings import guardrail_config

logger = logging.getLogger(__name__)


@dataclass
class GuardrailResult:
    passed: bool
    reason: str = ""
    sanitised_text: str = ""


# ------------------------------------------------------------------
# PII redaction patterns
# ------------------------------------------------------------------
_PII_PATTERNS = [
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[EMAIL REDACTED]"),
    (re.compile(r"\b\d{10,12}\b"), "[PHONE REDACTED]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN REDACTED]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[CARD REDACTED]"),
    (re.compile(r"\b[A-Z]{2}\d{7}\b"), "[PASSPORT REDACTED]"),
]


def _redact_pii(text: str) -> str:
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ------------------------------------------------------------------
# Input guardrail
# ------------------------------------------------------------------
def validate_input(user_input: str) -> GuardrailResult:
    """Validate and sanitise raw user input before sending to the LLM."""

    # 1. Length check
    if len(user_input) > guardrail_config.max_input_length:
        return GuardrailResult(
            passed=False,
            reason=f"Input exceeds maximum length of {guardrail_config.max_input_length} characters.",
        )

    text_lower = user_input.lower()

    # 2. Prompt injection / jailbreak detection
    for pattern in guardrail_config.injection_patterns:
        if pattern.lower() in text_lower:
            logger.warning("Prompt injection detected: '%s'", pattern)
            return GuardrailResult(
                passed=False,
                reason="Your message contains instructions that cannot be processed by this educational assistant.",
            )

    # 3. Hard-blocked content
    for keyword in guardrail_config.blocked_content_keywords:
        if keyword.lower() in text_lower:
            logger.warning("Blocked content keyword detected: '%s'", keyword)
            return GuardrailResult(
                passed=False,
                reason="Your message contains content that is not permitted in this learning environment.",
            )

    # 4. PII redaction in input (protect student data from being echoed back)
    sanitised = _redact_pii(user_input)

    return GuardrailResult(passed=True, sanitised_text=sanitised)


# ------------------------------------------------------------------
# Output guardrail
# ------------------------------------------------------------------
def validate_output(llm_response: str) -> GuardrailResult:
    """Sanitise and validate LLM output before returning to the student."""

    # 1. Length cap
    if len(llm_response) > guardrail_config.max_output_length:
        llm_response = llm_response[: guardrail_config.max_output_length] + "\n\n[Response truncated for safety.]"

    text_lower = llm_response.lower()

    # 2. Check the model didn't accidentally produce blocked content
    for keyword in guardrail_config.blocked_content_keywords:
        if keyword.lower() in text_lower:
            logger.error("Blocked keyword found in LLM output – suppressing response.")
            return GuardrailResult(
                passed=False,
                reason="The generated response was flagged and cannot be shown.",
            )

    # 3. Redact any PII that leaked into the response
    sanitised = _redact_pii(llm_response)

    return GuardrailResult(passed=True, sanitised_text=sanitised)


# ------------------------------------------------------------------
# Topic relevance check (lightweight keyword heuristic)
# ------------------------------------------------------------------
# Non-educational patterns that should be caught even if they contain question words
_NON_EDU_PATTERNS = re.compile(
    r"\b(pizza|burger|food|recipe|restaurant|movie|film|music|song|sport|"
    r"weather|stock|crypto|bitcoin|celebrity|gossip|game|gaming|lottery|"
    r"shopping|fashion|travel|vacation|holiday|joke|meme|tiktok|instagram|"
    r"facebook|twitter|dating|relationship advice|horoscope)\b",
    re.IGNORECASE,
)


def is_educational_topic(user_input: str) -> Tuple[bool, str]:
    """
    Return (True, '') if the message appears educational,
    or (False, reason) if it looks off-topic.
    """
    text_lower = user_input.lower()

    # Hard-reject clearly non-educational subjects first
    if _NON_EDU_PATTERNS.search(text_lower):
        return (
            False,
            "I'm designed to help with educational topics only. "
            "Please ask me about subjects, concepts, or exam preparation.",
        )

    # Allow if an explicit academic topic keyword is present
    for topic in guardrail_config.allowed_topics:
        if topic in text_lower:
            return True, ""

    # Allow general question words (what/why/how/explain etc.)
    question_words = ["what", "why", "how", "explain", "describe",
                      "define", "solve", "calculate", "compare", "summarise", "summarize"]
    for word in question_words:
        if re.search(rf"\b{word}\b", text_lower):
            return True, ""

    return (
        False,
        "I'm designed to help with educational topics only. "
        "Please ask me about subjects, concepts, or exam preparation.",
    )
