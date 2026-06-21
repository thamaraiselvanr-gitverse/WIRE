"""
Intent Reconciler — Dual-Input (URL + Free-Text) Reconciliation.

Parses user's free-text intent and maps extracted fields to existing
slot_id bindings in the URL-derived schema. HARD RULE: may only modify
properties of EXISTING fields/sections — never fabricates a field
without a real slot_id.
"""

import re
import structlog
from typing import Dict, List, Optional

from wire.schema.semantic_schema import (
    SectionRole,
    WebsiteFormSchema,
    FormField,
)
from wire.semantic.llm_guard import LLMGuard

logger = structlog.get_logger(__name__)

# ── Keyword-to-SectionRole mapping for heuristic intent extraction ──────

_INTENT_KEYWORDS: Dict[str, SectionRole] = {
    "portfolio": SectionRole.PORTFOLIO,
    "work": SectionRole.PORTFOLIO,
    "projects": SectionRole.PORTFOLIO,
    "showcase": SectionRole.PORTFOLIO,
    "gallery": SectionRole.MEDIA_GALLERY,
    "about": SectionRole.ABOUT,
    "bio": SectionRole.ABOUT,
    "biography": SectionRole.ABOUT,
    "story": SectionRole.ABOUT,
    "contact": SectionRole.CONTACT,
    "email": SectionRole.CONTACT,
    "phone": SectionRole.CONTACT,
    "service": SectionRole.SERVICES,
    "services": SectionRole.SERVICES,
    "offering": SectionRole.SERVICES,
    "pricing": SectionRole.PRICING,
    "price": SectionRole.PRICING,
    "plan": SectionRole.PRICING,
    "testimonial": SectionRole.TESTIMONIALS,
    "review": SectionRole.TESTIMONIALS,
    "team": SectionRole.TEAM,
    "staff": SectionRole.TEAM,
    "blog": SectionRole.BLOG_FEED,
    "news": SectionRole.BLOG_FEED,
    "faq": SectionRole.FAQ,
    "questions": SectionRole.FAQ,
    "feature": SectionRole.FEATURE_GRID,
    "features": SectionRole.FEATURE_GRID,
    "social": SectionRole.SOCIAL_LINKS,
    "social media": SectionRole.SOCIAL_LINKS,
}

# ── Role domain extraction patterns ─────────────────────────────────────

_ROLE_PATTERNS = [
    r"i(?:'m| am) (?:a |an )?(.+?)(?:\.|,|$)",
    r"(?:for|about) (?:a |an |my )?(.+?)(?:\.|,| with| who| that|$)",
    r"(?:this is|it's) (?:a |an |my )?(.+?)(?:'s| site| website| page|\.|,|$)",
    r"(?:building|creating|making) (?:a |an |my )?(.+?)(?:\.|,| site| website|$)",
]


class IntentReconciler:
    """
    Reconciles URL-derived form schema with user's free-text intent.

    Generalized: handles ANY site-type framing ("I'm a photographer,"
    "I'm opening a bakery," "this is a SaaS product"). May only modify
    properties of EXISTING fields/sections — never fabricates a field
    without a real slot_id.
    """

    def __init__(self, llm_guard: LLMGuard):
        self.llm_guard = llm_guard

    def reconcile(
        self,
        form_schema: WebsiteFormSchema,
        intent_prompt: Optional[str] = None,
    ) -> WebsiteFormSchema:
        """
        Apply user intent to the form schema.

        If intent_prompt is None/empty, returns form_schema unmodified.
        Otherwise, extracts structured intent and applies modifications
        to existing fields only.
        """
        if not intent_prompt or not intent_prompt.strip():
            logger.info("intent_reconciler_no_intent")
            return form_schema

        intent = self._extract_intent(intent_prompt)
        if intent is None:
            logger.warning("intent_reconciler_extraction_failed")
            form_schema.unsupported_requests.append(
                f"Could not parse intent: {intent_prompt[:100]}"
            )
            return form_schema

        return self._apply_intent(form_schema, intent)

    def _extract_intent(self, intent_prompt: str) -> Optional[dict]:
        """
        Extract structured intent from free-text.

        Architecture: LLM-first, heuristic-fallback.
        1. Try live LLM extraction via llm_guard.call_intent()
        2. If LLM unavailable or fails, fall back to heuristic keywords
        """
        # ── Attempt live LLM extraction first ───────────────────────────
        llm_result = self.llm_guard.call_intent(intent_prompt)
        if llm_result is not None:
            logger.info(
                "intent_extracted_llm",
                user_role_domain=llm_result.get("user_role_domain"),
                emphasize=llm_result.get("sections_to_emphasize"),
                exclude=llm_result.get("sections_to_exclude"),
            )
            return llm_result

        # ── Heuristic fallback ──────────────────────────────────────────
        logger.info("intent_reconciler_llm_unavailable_using_heuristic")
        prompt_lower = intent_prompt.lower().strip()

        # Extract user role/domain
        user_role_domain = None
        for pattern in _ROLE_PATTERNS:
            match = re.search(pattern, prompt_lower)
            if match:
                user_role_domain = match.group(1).strip()
                break

        # Extract section emphasis via keyword matching
        sections_to_emphasize: List[str] = []
        sections_to_deprioritize: List[str] = []
        sections_to_exclude: List[str] = []

        for keyword, role in _INTENT_KEYWORDS.items():
            if keyword in prompt_lower:
                # Check for negation context
                negation_pattern = rf"(?:no|without|remove|exclude|don't need|skip)\s+(?:\w+\s+)*{re.escape(keyword)}"
                if re.search(negation_pattern, prompt_lower):
                    sections_to_exclude.append(role.value)
                else:
                    sections_to_emphasize.append(role.value)

        # Deduplicate
        sections_to_emphasize = list(dict.fromkeys(sections_to_emphasize))
        sections_to_exclude = list(dict.fromkeys(sections_to_exclude))

        intent = {
            "user_role_domain": user_role_domain,
            "sections_to_emphasize": sections_to_emphasize,
            "sections_to_deprioritize": sections_to_deprioritize,
            "sections_to_exclude": sections_to_exclude,
            "explicit_field_overrides": [],
        }

        logger.info(
            "intent_extracted_heuristic",
            user_role_domain=user_role_domain,
            emphasize=sections_to_emphasize,
            exclude=sections_to_exclude,
        )
        return intent

    def _apply_intent(
        self, schema: WebsiteFormSchema, intent: dict
    ) -> WebsiteFormSchema:
        """
        Apply extracted intent to the schema.

        Only modifies properties of EXISTING fields/sections.
        Unmatched requests → unsupported_requests.
        """
        sections_to_exclude = set(intent.get("sections_to_exclude", []))
        sections_to_emphasize = set(intent.get("sections_to_emphasize", []))

        existing_roles = {f.section_role.value for f in schema.fields}

        # Track what was unmatched
        for role in sections_to_emphasize:
            if role not in existing_roles:
                schema.unsupported_requests.append(
                    f"Emphasized section '{role}' has no corresponding fields in schema"
                )

        for role in sections_to_exclude:
            if role not in existing_roles:
                schema.unsupported_requests.append(
                    f"Excluded section '{role}' was not present in schema"
                )

        # Apply exclusions: mark excluded section fields as not required
        for field in schema.fields:
            if field.section_role.value in sections_to_exclude:
                field.required = False

        # Apply overrides
        overrides = intent.get("explicit_field_overrides", [])
        for override in overrides:
            field_id = override.get("field_id")
            if field_id:
                for field in schema.fields:
                    if field.field_id == field_id:
                        if "required" in override:
                            field.required = override["required"]
                        break
                else:
                    schema.unsupported_requests.append(
                        f"Field override for '{field_id}' — field not found"
                    )

        # Build reconciliation summary
        parts = []
        user_role = intent.get("user_role_domain")
        if user_role:
            parts.append(f"User role/domain: {user_role}")
        if sections_to_emphasize:
            parts.append(f"Emphasized: {', '.join(sections_to_emphasize)}")
        if sections_to_exclude:
            parts.append(f"Excluded: {', '.join(sections_to_exclude)}")
        if schema.unsupported_requests:
            parts.append(f"Unsupported requests: {len(schema.unsupported_requests)}")

        schema.reconciliation_summary = "; ".join(parts) if parts else None

        logger.info(
            "intent_applied",
            excluded=len(sections_to_exclude),
            emphasized=len(sections_to_emphasize),
            unsupported=len(schema.unsupported_requests),
        )
        return schema
