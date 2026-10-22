"""Built-in redaction rules."""

from logprivacy.rules.base import RedactionRule, RegexRedactionRule
from logprivacy.rules.credential import CredentialRule
from logprivacy.rules.credit_card import CreditCardRule
from logprivacy.rules.custom import CustomRegexRule
from logprivacy.rules.email import EmailRule
from logprivacy.rules.ip_address import IPAddressRule
from logprivacy.rules.phone import PhoneRule
from logprivacy.rules.secret import SecretRule
from logprivacy.rules.token import TokenRule
from logprivacy.rules.url import UrlRule

__all__ = [
    "CredentialRule",
    "CreditCardRule",
    "CustomRegexRule",
    "EmailRule",
    "IPAddressRule",
    "PhoneRule",
    "RegexRedactionRule",
    "RedactionRule",
    "SecretRule",
    "TokenRule",
    "UrlRule",
]
