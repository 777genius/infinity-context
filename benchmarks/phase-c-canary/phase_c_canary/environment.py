from __future__ import annotations

from collections.abc import Mapping

from .authority import AuthorityContract


class EnvironmentError(ValueError):
    pass


_COMMON = frozenset({"PATH", "LANG", "LC_ALL", "TZ"})


def build_runtime_environment(
    explicit: Mapping[str, str], *, required: frozenset[str]
) -> dict[str, str]:
    """Build a child environment only from explicitly supplied values.

    The ambient process environment is deliberately not an input.
    """
    allowed = _COMMON | required
    unexpected = set(explicit) - allowed
    missing = required - set(explicit)
    if unexpected:
        raise EnvironmentError(f"unexpected environment keys: {sorted(unexpected)}")
    if missing:
        raise EnvironmentError(f"missing environment keys: {sorted(missing)}")
    if any(not isinstance(value, str) or "\x00" in value for value in explicit.values()):
        raise EnvironmentError("environment values must be NUL-free strings")
    return {key: explicit[key] for key in sorted(explicit)}


def offline_environment(explicit: Mapping[str, str] | None = None) -> dict[str, str]:
    return build_runtime_environment(explicit or {}, required=frozenset())


def immutable_python_environment(*, authority: AuthorityContract, path: str) -> dict[str, str]:
    from .python_closure import immutable_infinity_python_path

    return build_runtime_environment(
        {
            "PATH": path,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONPATH": immutable_infinity_python_path(authority),
            "PYTHONSAFEPATH": "1",
        },
        required=frozenset(
            {"PYTHONDONTWRITEBYTECODE", "PYTHONNOUSERSITE", "PYTHONPATH", "PYTHONSAFEPATH"}
        ),
    )
