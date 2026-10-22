"""Ready-to-use rule sets."""

from logprivacy.rule_sets.default import default_rules
from logprivacy.rule_sets.strict import strict_rules
from logprivacy.rule_sets.web import web_rules

__all__ = ["default_rules", "strict_rules", "web_rules"]
