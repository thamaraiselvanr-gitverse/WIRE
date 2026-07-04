"""
LLM Client — Thin Wrapper Around Google Generative AI (Gemini).

Provides structured, JSON-mode LLM calls for the semantic layer.
All calls go through LLMGuard for input preparation and output
validation — this module handles only the transport layer.
"""

import json
import os
from typing import Optional

import google.generativeai as genai
import structlog

logger = structlog.get_logger(__name__)

# Default model — can be overridden via environment variable
_DEFAULT_MODEL = "gemini-2.0-flash"


class LLMClient:
    """
    Thin wrapper around Google Generative AI for structured output.

    Configured via GEMINI_API_KEY environment variable. If no key is
    set, all calls return None (graceful degradation, not a crash).
    """

    def __init__(self, model_name: Optional[str] = None):
        self._model_name = model_name or os.environ.get(
            "WIRE_LLM_MODEL", _DEFAULT_MODEL
        )
        self._api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get(
            "GOOGLE_API_KEY"
        )
        self._model = None

        if self._api_key:
            try:
                genai.configure(api_key=self._api_key)
                self._model = genai.GenerativeModel(self._model_name)
                logger.info(
                    "llm_client_initialized",
                    model=self._model_name,
                )
            except Exception as e:
                logger.error("llm_client_init_failed", error=str(e))
                self._model = None
        else:
            logger.warning(
                "llm_client_no_api_key",
                hint="Set GEMINI_API_KEY or GOOGLE_API_KEY to enable LLM features",
            )

    @property
    def is_available(self) -> bool:
        """Whether the LLM client is configured and ready."""
        return self._model is not None

    def generate_json(
        self,
        system_instruction: str,
        user_content: str,
        temperature: float = 0.1,
    ) -> Optional[dict]:
        """
        Generate a structured JSON response from the LLM.

        Uses Gemini's JSON response mode for constrained output.
        Returns None if the LLM is unavailable or the response is
        not valid JSON (fail-closed).
        """
        if not self.is_available:
            return None

        try:
            model_with_config = genai.GenerativeModel(
                self._model_name,
                system_instruction=system_instruction,
                generation_config=genai.GenerationConfig(
                    response_mime_type="application/json",
                    temperature=temperature,
                ),
            )

            response = model_with_config.generate_content(user_content)

            if not response.text:
                logger.warning("llm_client_empty_response")
                return None

            result = json.loads(response.text)
            if not isinstance(result, dict):
                logger.warning(
                    "llm_client_non_dict_response", type=type(result).__name__
                )
                return None

            logger.info("llm_client_response_received", keys=list(result.keys()))
            return result

        except json.JSONDecodeError as e:
            logger.warning("llm_client_json_parse_error", error=str(e))
            return None
        except Exception as e:
            logger.error("llm_client_call_error", error=str(e))
            return None
