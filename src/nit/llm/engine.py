"""LLMEngine — abstract interface for LLM generation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMResponse:
    """Result from an LLM generation call."""

    text: str
    """The generated text content."""

    model: str
    """Model identifier that produced the response."""

    prompt_tokens: int = 0
    """Number of tokens in the prompt."""

    completion_tokens: int = 0
    """Number of tokens in the completion."""

    @property
    def total_tokens(self) -> int:
        """Total tokens consumed (prompt + completion)."""
        return self.prompt_tokens + self.completion_tokens


@dataclass
class LLMMessage:
    """A single message in a conversation."""

    role: str
    """One of ``'system'``, ``'user'``, or ``'assistant'``."""

    content: str
    """Text content of the message."""


@dataclass
class GenerationRequest:
    """Parameters for an LLM generation call."""

    messages: list[LLMMessage]
    """Conversation messages to send to the model."""

    model: str | None = None
    """Override the default model for this request."""

    temperature: float = 0.2
    """Sampling temperature (lower = more deterministic)."""

    max_tokens: int = 4096
    """Maximum tokens to generate."""

    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)
    """Structured metadata forwarded to provider calls when supported."""

    extra: dict[str, object] = field(default_factory=dict)
    """Provider-specific extra parameters."""


class LLMEngine(ABC):
    """Abstract interface for LLM generation.

    All LLM adapters (built-in LiteLLM, CLI tool delegation, etc.)
    must implement this interface.
    """

    @abstractmethod
    async def generate(self, request: GenerationRequest) -> LLMResponse:
        """Send a generation request and return the response.

        Args:
            request: The generation parameters including messages and model config.

        Returns:
            The LLM response with generated text and token usage.

        Raises:
            LLMError: On any LLM-related failure (network, auth, rate limit, etc.).
        """

    @abstractmethod
    async def generate_text(self, prompt: str, *, context: str = "") -> str:
        """Convenience method: send a simple prompt and return the text.

        Args:
            prompt: The user prompt.
            context: Optional system context to prepend.

        Returns:
            The generated text string.
        """

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the default model identifier for this engine."""


class LLMError(Exception):
    """Base exception for LLM-related errors."""


class LLMAuthError(LLMError):
    """Raised when authentication fails (invalid or missing API key)."""


class LLMRateLimitError(LLMError):
    """Raised when the provider rate limit is hit."""


class LLMConnectionError(LLMError):
    """Raised when the provider cannot be reached."""
