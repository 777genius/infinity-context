"""Compatibility exports for the public deterministic sensitive-text policy."""

import re as re

from infinity_context_core.sensitive_text import (
    _SECRET_PATTERNS as _SECRET_PATTERNS,
)
from infinity_context_core.sensitive_text import (
    _USERINFO_PATTERN as _USERINFO_PATTERN,
)
from infinity_context_core.sensitive_text import (
    contains_sensitive_text as contains_sensitive_text,
)
from infinity_context_core.sensitive_text import (
    redact_sensitive_text as redact_sensitive_text,
)
