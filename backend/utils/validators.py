# backend/utils/validators.py

from backend.api.models import QueryParameters


class ValidationError(Exception):
    """Custom validation error"""
    pass


def validate_query_parameters(params: QueryParameters) -> None:
    """
    Validate query parameters and raise ValidationError if invalid

    Args:
        params: Query parameters to validate

    Raises:
        ValidationError: If parameters are invalid
    """
    # Query text validation
    if not params.query or len(params.query.strip()) == 0:
        raise ValidationError("Query text cannot be empty")

    if len(params.query) > 500:
        raise ValidationError("Query text must be 500 characters or less")

    # Top K validation
    if params.top_k < 1 or params.top_k > 20:
        raise ValidationError("top_k must be between 1 and 20")

    # Max depth validation
    if params.max_depth < 1 or params.max_depth > 3:
        raise ValidationError("max_depth must be between 1 and 3")

    # Web concurrency validation
    if params.web_concurrency < 1 or params.web_concurrency > 20:
        raise ValidationError("web_concurrency must be between 1 and 20")

    # Corpus directory validation
    if params.corpus_dir:
        import os
        if not os.path.isdir(params.corpus_dir):
            raise ValidationError(f"Corpus directory does not exist: {params.corpus_dir}")


def sanitize_input(text: str) -> str:
    """
    Sanitize user input to prevent injection attacks

    Args:
        text: Input text to sanitize

    Returns:
        Sanitized text
    """
    # Remove potentially dangerous characters
    dangerous_chars = ['<', '>', '{', '}', '|', '\\', '^', '~', '[', ']', '`']
    sanitized = text

    for char in dangerous_chars:
        sanitized = sanitized.replace(char, '')

    return sanitized.strip()
