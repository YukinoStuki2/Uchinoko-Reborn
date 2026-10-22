"""Default placeholder values used when sensitive data is redacted."""

EMAIL_PLACEHOLDER = "[EMAIL]"
URL_PLACEHOLDER = "[URL]"
SECRET_PLACEHOLDER = "[SECRET]"
TOKEN_PLACEHOLDER = "[TOKEN]"
IP_ADDRESS_PLACEHOLDER = "[IP_ADDRESS]"
PHONE_PLACEHOLDER = "[PHONE]"

DEFAULT_PLACEHOLDERS: dict[str, str] = {
    "email": EMAIL_PLACEHOLDER,
    "url": URL_PLACEHOLDER,
    "secret": SECRET_PLACEHOLDER,
    "credential": SECRET_PLACEHOLDER,
    "token": TOKEN_PLACEHOLDER,
    "ip_address": IP_ADDRESS_PLACEHOLDER,
    "phone": PHONE_PLACEHOLDER,
    "credit_card": "[CREDIT_CARD]",
}
