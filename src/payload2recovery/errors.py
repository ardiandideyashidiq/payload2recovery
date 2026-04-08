class Payload2RecoveryError(RuntimeError):
    """Base error for user-facing failures."""


class ValidationError(Payload2RecoveryError):
    """Raised when input or environment validation fails."""


class UnsupportedLayoutError(Payload2RecoveryError):
    """Raised when the requested recovery package shape is unsafe."""
