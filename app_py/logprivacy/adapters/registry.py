"""Public adapter registry for custom structured-data conversion."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeAlias

AdapterConverter: TypeAlias = Callable[[object], object]

_SAFE_TYPE_NAME_PATTERN = re.compile(r"[^A-Za-z0-9_.-]+")

# Types handled directly by the core pipeline; adapters must not override them.
_RESERVED_TYPES: frozenset[type[object]] = frozenset(
    {
        object,
        str,
        int,
        float,
        bool,
        bytes,
        bytearray,
        memoryview,
        dict,
        list,
        tuple,
        set,
        frozenset,
    }
)


@dataclass(frozen=True, slots=True)
class _AdapterResolution:
    """Internal result of an adapter resolution attempt.

    ``converter`` is the callable to use, or ``None`` when no adapter matched.
    ``resolution_failed`` is ``True`` when ``__instancecheck__`` raised during
    the virtual-type scan; in that case the resolution is not fully reliable and
    the caller must mark ``adapter_error`` and not execute the converter.
    """

    converter: AdapterConverter | None = None
    resolution_failed: bool = False


@dataclass(slots=True)
class AdapterRegistry:
    """Registry mapping Python types to converters used by ``to_safe_data()``.

    Adapters are intended for application classes, external library types, and
    custom subclasses.  Built-in types handled directly by the core pipeline
    (``str``, ``int``, ``dict``, ``list``, etc.) are reserved and cannot be
    registered.  A custom subclass such as ``class ExternalList(list)`` *can*
    be registered; ``list`` itself cannot.

    Adapter dispatch for custom subclasses happens **before** the built-in
    structural handlers (Mapping, list/tuple, set/frozenset), so a registered
    converter always takes precedence over the native fallback.

    ``default()`` returns a fresh registry so applications and tests can add
    converters without mutating shared global state.
    """

    _converters: dict[type[object], AdapterConverter] = field(default_factory=dict)

    @classmethod
    def default(cls) -> AdapterRegistry:
        """Return a new registry with the built-in core behavior."""
        return cls()

    def copy(self) -> AdapterRegistry:
        """Return an independent copy of this registry."""
        return AdapterRegistry(dict(self._converters))

    def register(self, value_type: type[object], converter: AdapterConverter) -> AdapterRegistry:
        """Register ``converter`` for ``value_type`` and return this registry.

        Raises ``TypeError`` when ``value_type`` is not a type or ``converter``
        is not callable.  Raises ``ValueError`` when ``value_type`` is one of
        the built-in types reserved for the core pipeline.

        The converter result is never trusted directly; it is fed back through
        the normal sanitization pipeline.
        """
        if not isinstance(value_type, type):
            raise TypeError("adapter type must be a type")
        if not callable(converter):
            raise TypeError("adapter converter must be callable")
        if value_type in _RESERVED_TYPES:
            raise ValueError(
                f"adapter type cannot be a reserved built-in type: {value_type.__name__!r}. "
                "Register a custom subclass instead."
            )
        self._converters[value_type] = converter
        return self

    def resolve(self, value: object) -> AdapterConverter | None:
        """Return the best converter for ``value`` or ``None``.

        Resolution order:
        1. Concrete type registered directly (MRO walk, no ``isinstance``).
        2. Abstract / virtual base classes in registration order.

        ``__instancecheck__`` calls are protected.  A metaclass that raises
        during ``isinstance`` is treated as non-matching.  Use
        ``_resolve_result()`` when you need to distinguish "no match" from
        "resolution failed".
        """
        return self._resolve_result(value).converter

    def _resolve_result(self, value: object) -> _AdapterResolution:
        """Return a resolution result distinguishing success, failure, and no-match.

        Resolution order:
        1. Concrete type and MRO bases (direct dict lookup — never raises).
        2. Virtual / abstract base classes in registration order (protected
           ``isinstance`` calls — a metaclass that raises sets
           ``resolution_failed=True`` and the normalizer marks ``adapter_error``).

        When ``resolution_failed`` is ``True`` the caller must mark
        ``adapter_error`` and not execute any converter.
        """
        value_type = type(value)

        # Phase 1: MRO-based lookup (safe — pure dict lookup, no user code).
        for candidate in value_type.__mro__:
            converter = self._converters.get(candidate)
            if converter is not None:
                return _AdapterResolution(converter=converter)

        # Phase 2: virtual / abstract base class scan (may call __instancecheck__).
        resolution_failed = False
        for registered_type, converter in self._converters.items():
            try:
                matches = isinstance(value, registered_type)
            except Exception:
                # __instancecheck__ raised — resolution is not fully reliable.
                # Record the failure; do NOT use this or any subsequent converter.
                resolution_failed = True
                continue
            if matches:
                if resolution_failed:
                    # A prior failure makes the overall resolution unreliable.
                    break
                return _AdapterResolution(converter=converter)

        if resolution_failed:
            return _AdapterResolution(resolution_failed=True)
        return _AdapterResolution()
