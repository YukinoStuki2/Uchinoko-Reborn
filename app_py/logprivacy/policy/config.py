"""Configuration object for LogPrivacy."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from logprivacy.path_rules import PathRule

from logprivacy.exceptions.errors import PolicyConfigurationError
from logprivacy.field_rules import FieldRule
from logprivacy.internal.traversal import safe_mapping_key_text
from logprivacy.masking.strategy import (
    HashMaskingStrategy,
    HMACMaskingStrategy,
    MaskingStrategy,
    PartialMaskingStrategy,
    PlaceholderMaskingStrategy,
)
from logprivacy.rules.base import RedactionRule

MaskingChoice = Literal["placeholder", "partial", "hash"]
_BasePolicyName = Literal["default", "strict", "web", "production", "none"]

_SCHEMA_VERSION = 1
_SUPPORTED_BASES: tuple[_BasePolicyName, ...] = (
    "default",
    "strict",
    "web",
    "production",
    "none",
)
_DECLARATIVE_FIELDS = frozenset(
    {
        "schema_version",
        "base",
        "field_rules",
        "path_rules",
        "allowlist",
        "sensitive_keys",
        "max_depth",
        "max_items",
        "max_findings",
        "block_categories",
        "masking",
        "clean_mapping_keys",
        "clean_unknown_objects",
    }
)

_DEFAULT_SENSITIVE_KEYS = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "access_token",
    "refresh_token",
    "client_secret",
    "private_key",
    "authorization",
    "cookie",
    "set-cookie",
)


def _default_rules_sentinel() -> tuple[RedactionRule, ...]:
    """Return the internal sentinel for an omitted rules argument."""
    return _RULES_NOT_PROVIDED


class _RulesNotProvided(tuple):  # type: ignore[type-arg]
    """Singleton sentinel indicating that built-in default rules are required."""


_RULES_NOT_PROVIDED = _RulesNotProvided()


def resolve_masking(masking: MaskingStrategy | MaskingChoice) -> MaskingStrategy:
    """Return a masking strategy from a strategy object or a simple name."""
    if not isinstance(masking, str):
        return masking
    if masking == "placeholder":
        return PlaceholderMaskingStrategy()
    if masking == "partial":
        return PartialMaskingStrategy()
    if masking == "hash":
        return HashMaskingStrategy()
    raise ValueError("Unknown masking strategy")


@dataclass(frozen=True, slots=True)
class CleanerPolicy:
    """Configuration for a :class:`logprivacy.cleaner.Cleaner` instance."""

    rules: tuple[RedactionRule, ...] = field(default_factory=_default_rules_sentinel)
    masking: MaskingStrategy = field(default_factory=PlaceholderMaskingStrategy)
    sensitive_keys: tuple[str, ...] = _DEFAULT_SENSITIVE_KEYS
    field_rules: tuple[FieldRule, ...] = ()
    path_rules: tuple[object, ...] = ()
    allowlist: tuple[str, ...] | None = None
    pseudonymizer: HMACMaskingStrategy | None = field(default=None, repr=False)
    block_categories: tuple[str, ...] = ()
    clean_mapping_keys: bool = False
    max_depth: int = 20
    max_items: int = 10_000
    max_findings: int = 1_000
    clean_unknown_objects: bool = False

    def __post_init__(self) -> None:
        """Validate policy values and load default rules when omitted."""
        _validate_non_negative_integer("max_depth", self.max_depth)
        _validate_positive_integer("max_items", self.max_items)
        _validate_positive_integer("max_findings", self.max_findings)
        _validate_string_tuple("sensitive_keys", self.sensitive_keys)
        _validate_string_tuple("block_categories", self.block_categories)
        _validate_boolean("clean_mapping_keys", self.clean_mapping_keys)
        _validate_boolean("clean_unknown_objects", self.clean_unknown_objects)
        _validate_field_rules(self.field_rules)
        _validate_path_rules(self.path_rules)
        if self.allowlist is not None:
            _validate_allowlist_paths(self.allowlist)

        if type(self.rules) is _RulesNotProvided:
            object.__setattr__(self, "rules", _load_default_rules())

    @classmethod
    def default(cls, *, masking: MaskingStrategy | MaskingChoice = "placeholder") -> CleanerPolicy:
        """Return the balanced default policy."""
        return cls(rules=_load_default_rules(), masking=resolve_masking(masking))

    @classmethod
    def strict(cls, *, masking: MaskingStrategy | MaskingChoice = "placeholder") -> CleanerPolicy:
        """Return a stricter policy for sensitive environments."""
        return cls(rules=_load_strict_rules(), masking=resolve_masking(masking))

    @classmethod
    def web(cls, *, masking: MaskingStrategy | MaskingChoice = "placeholder") -> CleanerPolicy:
        """Return a policy focused on web and HTTP logs."""
        return cls(rules=_load_web_rules(), masking=resolve_masking(masking))

    @classmethod
    def production(cls) -> CleanerPolicy:
        """Return a strict policy that blocks high-risk categories."""
        return cls.strict().block("credential", "token", "secret", "credit_card")

    def add_rules(self, *rules: RedactionRule) -> CleanerPolicy:
        """Return a new policy with rules appended."""
        return replace(self, rules=(*self.rules, *rules))

    def with_rules(self, *rules: RedactionRule) -> CleanerPolicy:
        """Return a new policy using exactly the given text rules."""
        return replace(self, rules=tuple(rules))

    def with_masking(self, masking: MaskingStrategy | MaskingChoice) -> CleanerPolicy:
        """Return a new policy with another masking strategy."""
        return replace(self, masking=resolve_masking(masking))

    def add_field_rules(self, *rules: FieldRule) -> CleanerPolicy:
        """Return a new policy with structured field rules appended."""
        return replace(self, field_rules=(*self.field_rules, *rules))

    def with_field_rules(self, *rules: FieldRule) -> CleanerPolicy:
        """Return a new policy using exactly the given field rules."""
        return replace(self, field_rules=tuple(rules))

    def add_path_rules(self, *rules: object) -> CleanerPolicy:
        """Return a new policy with path rules appended."""
        return replace(self, path_rules=(*self.path_rules, *rules))

    def with_path_rules(self, *rules: object) -> CleanerPolicy:
        """Return a new policy using exactly the given path rules."""
        return replace(self, path_rules=tuple(rules))

    def allow_paths(self, *paths: str) -> CleanerPolicy:
        """Return a new policy with an allowlist of permitted paths."""
        return replace(self, allowlist=tuple(paths))

    def with_pseudonymizer(self, pseudonymizer: HMACMaskingStrategy) -> CleanerPolicy:
        """Return a new policy with a pseudonymizer for structured actions."""
        return replace(self, pseudonymizer=pseudonymizer)

    def block(self, *categories: str) -> CleanerPolicy:
        """Return a new policy that blocks selected categories."""
        return replace(
            self,
            block_categories=tuple(dict.fromkeys((*self.block_categories, *categories))),
        )

    def without_categories(self, *categories: str) -> CleanerPolicy:
        """Return a new policy with selected text-rule categories disabled."""
        blocked = set(categories)
        return replace(
            self,
            rules=tuple(rule for rule in self.rules if rule.category not in blocked),
        )

    def is_sensitive_key(self, key: object) -> bool:
        """Return whether a mapping key requires fail-closed value redaction."""
        key_text, trusted = safe_mapping_key_text(key)
        if not trusted:
            return True
        normalized = key_text.strip().casefold().replace("-", "_")
        sensitive = {item.casefold().replace("-", "_") for item in self.sensitive_keys}
        return normalized in sensitive

    @classmethod
    def from_dict(cls, data: object) -> CleanerPolicy:
        """Build a policy from a strictly validated schema-version-1 mapping.

        Every accepted field is applied. Unknown fields and invalid values fail
        closed with a safe configuration-path error; source values are not echoed.
        The optional ``pseudonymizer`` is intentionally not part of the schema and
        must be injected separately with :meth:`with_pseudonymizer`.
        """
        mapping = _require_mapping(data, "policy configuration")
        _validate_string_keys(mapping, "policy configuration")

        unknown = set(mapping) - _DECLARATIVE_FIELDS
        if unknown:
            raise PolicyConfigurationError(
                "unknown policy configuration fields: " + ", ".join(_sorted_string_values(unknown))
            )

        schema_version = mapping.get("schema_version")
        if schema_version != _SCHEMA_VERSION:
            raise PolicyConfigurationError(
                "unsupported schema_version; only version 1 is supported"
            )

        policy = _policy_from_base(mapping.get("base", "default"))

        if "masking" in mapping:
            masking = mapping["masking"]
            if not isinstance(masking, str) or masking not in {"placeholder", "partial", "hash"}:
                raise PolicyConfigurationError("invalid value at masking")
            policy = policy.with_masking(cast(MaskingChoice, masking))

        if "sensitive_keys" in mapping:
            sensitive_keys = _parse_string_list(mapping["sensitive_keys"], "sensitive_keys")
            policy = replace(policy, sensitive_keys=sensitive_keys)

        if "block_categories" in mapping:
            block_categories = _parse_string_list(mapping["block_categories"], "block_categories")
            policy = replace(
                policy,
                block_categories=tuple(dict.fromkeys(block_categories)),
            )

        if "max_depth" in mapping:
            policy = replace(
                policy,
                max_depth=_parse_non_negative_integer(mapping["max_depth"], "max_depth"),
            )
        if "max_items" in mapping:
            policy = replace(
                policy,
                max_items=_parse_positive_integer(mapping["max_items"], "max_items"),
            )
        if "max_findings" in mapping:
            policy = replace(
                policy,
                max_findings=_parse_positive_integer(mapping["max_findings"], "max_findings"),
            )
        if "clean_mapping_keys" in mapping:
            policy = replace(
                policy,
                clean_mapping_keys=_parse_boolean(
                    mapping["clean_mapping_keys"], "clean_mapping_keys"
                ),
            )
        if "clean_unknown_objects" in mapping:
            policy = replace(
                policy,
                clean_unknown_objects=_parse_boolean(
                    mapping["clean_unknown_objects"], "clean_unknown_objects"
                ),
            )

        raw_field_rules = mapping.get("field_rules", [])
        if not isinstance(raw_field_rules, list):
            raise PolicyConfigurationError("field_rules must be a list")
        field_rules = tuple(
            _parse_field_rule_dict(raw, index=index) for index, raw in enumerate(raw_field_rules)
        )
        if field_rules:
            policy = policy.add_field_rules(*field_rules)

        raw_path_rules = mapping.get("path_rules", [])
        if not isinstance(raw_path_rules, list):
            raise PolicyConfigurationError("path_rules must be a list")
        path_rules = tuple(
            _parse_path_rule_dict(raw, index=index) for index, raw in enumerate(raw_path_rules)
        )
        if path_rules:
            policy = policy.add_path_rules(*path_rules)

        raw_allowlist = mapping.get("allowlist")
        if raw_allowlist is not None:
            allowlist = _require_mapping(raw_allowlist, "allowlist")
            _validate_string_keys(allowlist, "allowlist")
            unknown_allowlist = set(allowlist) - {"paths"}
            if unknown_allowlist:
                raise PolicyConfigurationError(
                    "unknown allowlist fields: "
                    + ", ".join(_sorted_string_values(unknown_allowlist))
                )
            paths = _parse_string_list(allowlist.get("paths", []), "allowlist.paths")
            try:
                policy = policy.allow_paths(*paths)
            except (TypeError, ValueError) as exc:
                raise PolicyConfigurationError("invalid value at allowlist.paths") from exc

        return policy

    def to_dict(self) -> dict[str, object]:
        """Serialize all declaratively representable policy controls.

        Text rules must match one built-in base policy (or be empty). Custom text
        rules are rejected instead of being silently discarded. The HMAC
        pseudonymizer and its key are never exported; inject them after loading.
        """
        from logprivacy.path_rules import PathRule

        base = _declarative_base_for_rules(self.rules)
        result: dict[str, object] = {
            "schema_version": _SCHEMA_VERSION,
            "base": base,
            "masking": _declarative_masking_name(self.masking),
            "sensitive_keys": list(self.sensitive_keys),
            "block_categories": list(self.block_categories),
            "clean_mapping_keys": self.clean_mapping_keys,
            "clean_unknown_objects": self.clean_unknown_objects,
            "max_depth": self.max_depth,
            "max_items": self.max_items,
            "max_findings": self.max_findings,
            "field_rules": [
                {
                    "match": rule.match,
                    "mode": rule.mode,
                    "action": rule.action,
                    **({"max_chars": rule.max_chars} if rule.max_chars is not None else {}),
                    **({"category": rule.category} if rule.category else {}),
                }
                for rule in self.field_rules
            ],
            "path_rules": [
                {
                    "path": rule.path,
                    "mode": rule.mode,
                    "action": rule.action,
                    **({"max_chars": rule.max_chars} if rule.max_chars is not None else {}),
                    **({"category": rule.category} if rule.category else {}),
                }
                for rule in self.path_rules
                if isinstance(rule, PathRule)
            ],
        }
        if self.allowlist is not None:
            result["allowlist"] = {"paths": list(self.allowlist)}
        return result

    @classmethod
    def from_json(cls, text: str) -> CleanerPolicy:
        """Build a policy from JSON without reflecting source content in errors."""
        import json

        if not isinstance(text, str):
            raise TypeError("policy JSON must be a string")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise PolicyConfigurationError("invalid JSON policy configuration") from exc
        return cls.from_dict(data)

    def to_json(self, *, sort_keys: bool = True) -> str:
        """Serialize this policy to deterministic JSON."""
        import json

        return json.dumps(
            self.to_dict(),
            allow_nan=False,
            ensure_ascii=False,
            sort_keys=sort_keys,
            separators=(",", ":"),
        )


def _policy_from_base(value: object) -> CleanerPolicy:
    if not isinstance(value, str) or value not in _SUPPORTED_BASES:
        raise PolicyConfigurationError("unknown base policy")
    if value == "default":
        return CleanerPolicy.default()
    if value == "strict":
        return CleanerPolicy.strict()
    if value == "web":
        return CleanerPolicy.web()
    if value == "production":
        return CleanerPolicy.production()
    return CleanerPolicy(rules=())


def _declarative_base_for_rules(rules: tuple[RedactionRule, ...]) -> _BasePolicyName:
    signature = _rules_signature(rules)
    if not rules:
        return "none"
    if signature == _rules_signature(_load_default_rules()):
        return "default"
    if signature == _rules_signature(_load_strict_rules()):
        return "strict"
    if signature == _rules_signature(_load_web_rules()):
        return "web"
    raise PolicyConfigurationError(
        "policy text rules cannot be represented by the declarative schema"
    )


def _rules_signature(rules: tuple[RedactionRule, ...]) -> tuple[tuple[object, ...], ...]:
    signatures: list[tuple[object, ...]] = []
    for rule in rules:
        pattern = getattr(rule, "pattern", None)
        signatures.append(
            (
                type(rule).__module__,
                type(rule).__qualname__,
                getattr(rule, "name", None),
                getattr(rule, "category", None),
                getattr(pattern, "pattern", None),
                getattr(pattern, "flags", None),
                getattr(rule, "reason", None),
            )
        )
    return tuple(signatures)


def _declarative_masking_name(masking: MaskingStrategy) -> MaskingChoice:
    if isinstance(masking, PlaceholderMaskingStrategy) and masking == PlaceholderMaskingStrategy():
        return "placeholder"
    if isinstance(masking, PartialMaskingStrategy) and masking == PartialMaskingStrategy():
        return "partial"
    if isinstance(masking, HashMaskingStrategy) and masking == HashMaskingStrategy():
        return "hash"
    raise PolicyConfigurationError(
        "masking strategy cannot be represented by the declarative schema"
    )


def _require_mapping(value: object, path: str) -> dict[object, object]:
    if not isinstance(value, dict):
        raise PolicyConfigurationError(f"{path} must be a mapping")
    return value


def _validate_string_keys(mapping: dict[object, object], path: str) -> None:
    if any(not isinstance(key, str) for key in mapping):
        raise PolicyConfigurationError(f"{path} keys must be strings")


def _parse_string_list(value: object, path: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise PolicyConfigurationError(f"{path} must be a list")
    parsed: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise PolicyConfigurationError(f"{path}[{index}] must be a string")
        if not item.strip():
            raise PolicyConfigurationError(f"{path}[{index}] must be a non-empty string")
        parsed.append(item)
    return tuple(parsed)


def _sorted_string_values(values: set[object]) -> list[str]:
    """Return validated string values in deterministic order for safe errors."""
    return sorted(value for value in values if isinstance(value, str))


def _parse_non_negative_integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PolicyConfigurationError(f"invalid value at {path}")
    return value


def _parse_positive_integer(value: object, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise PolicyConfigurationError(f"invalid value at {path}")
    return value


def _parse_boolean(value: object, path: str) -> bool:
    if not isinstance(value, bool):
        raise PolicyConfigurationError(f"invalid value at {path}")
    return value


def _validate_non_negative_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to zero")


def _validate_positive_integer(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


def _validate_boolean(name: str, value: bool) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")


def _validate_string_tuple(name: str, values: tuple[str, ...]) -> None:
    if not isinstance(values, tuple):
        raise TypeError(f"{name} must be a tuple")
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise TypeError(f"{name} must contain only non-empty strings")


def _validate_field_rules(rules: tuple[FieldRule, ...]) -> None:
    for rule in rules:
        if not isinstance(rule, FieldRule):
            raise TypeError("field_rules must contain only FieldRule instances")


def _validate_path_rules(rules: tuple[object, ...]) -> None:
    from logprivacy.path_rules import PathRule

    for rule in rules:
        if not isinstance(rule, PathRule):
            raise TypeError("path_rules must contain only PathRule instances")


def _validate_allowlist_paths(paths: tuple[str, ...]) -> None:
    from logprivacy.path_rules.allowlist import _parse_allowlist_path

    for path in paths:
        _parse_allowlist_path(path)


def _parse_field_rule_dict(raw: object, *, index: int) -> FieldRule:
    prefix = f"field_rules[{index}]"
    mapping = _require_mapping(raw, prefix)
    _validate_string_keys(mapping, prefix)
    unknown = set(mapping) - {"match", "mode", "action", "max_chars", "category"}
    if unknown:
        raise PolicyConfigurationError(
            f"{prefix}: unknown fields: {', '.join(_sorted_string_values(unknown))}"
        )
    match = mapping.get("match")
    if not isinstance(match, str) or not match:
        raise PolicyConfigurationError(f"{prefix}.match must be a non-empty string")
    try:
        return FieldRule(
            match=match,
            mode=mapping.get("mode", "exact"),  # type: ignore[arg-type]
            action=mapping.get("action", "mask"),  # type: ignore[arg-type]
            max_chars=mapping.get("max_chars"),  # type: ignore[arg-type]
            category=mapping.get("category", ""),  # type: ignore[arg-type]
        )
    except (ValueError, TypeError) as exc:
        raise PolicyConfigurationError(f"invalid value at {prefix}") from exc


def _parse_path_rule_dict(raw: object, *, index: int) -> PathRule:
    from logprivacy.path_rules import PathRule

    prefix = f"path_rules[{index}]"
    mapping = _require_mapping(raw, prefix)
    _validate_string_keys(mapping, prefix)
    unknown = set(mapping) - {"path", "mode", "action", "max_chars", "category"}
    if unknown:
        raise PolicyConfigurationError(
            f"{prefix}: unknown fields: {', '.join(_sorted_string_values(unknown))}"
        )
    path_value = mapping.get("path")
    if not isinstance(path_value, str) or not path_value:
        raise PolicyConfigurationError(f"{prefix}.path must be a non-empty string")
    try:
        return PathRule(
            path=path_value,
            mode=mapping.get("mode", "exact"),  # type: ignore[arg-type]
            action=mapping.get("action", "mask"),  # type: ignore[arg-type]
            max_chars=mapping.get("max_chars"),  # type: ignore[arg-type]
            category=mapping.get("category", ""),  # type: ignore[arg-type]
        )
    except (ValueError, TypeError) as exc:
        raise PolicyConfigurationError(f"invalid value at {prefix}") from exc


def _load_default_rules() -> tuple[RedactionRule, ...]:
    from logprivacy.rule_sets.default import default_rules

    return default_rules()


def _load_strict_rules() -> tuple[RedactionRule, ...]:
    from logprivacy.rule_sets.strict import strict_rules

    return strict_rules()


def _load_web_rules() -> tuple[RedactionRule, ...]:
    from logprivacy.rule_sets.web import web_rules

    return web_rules()
