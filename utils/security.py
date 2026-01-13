"""
Security utilities: secret loading, masking, optional encryption hooks.
Placeholder implementation.
"""


def mask_secret(value: str) -> str:
    if not value:
        return ""
    # Keep last 4 chars visible
    return "***" + value[-4:]
