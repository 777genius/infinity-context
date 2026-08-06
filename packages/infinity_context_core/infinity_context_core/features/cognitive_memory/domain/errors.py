"""Domain errors for provider-neutral cognitive candidates."""


class CognitiveMemoryInvariantError(ValueError):
    """Raised when a cognitive candidate violates a locked trust invariant."""
