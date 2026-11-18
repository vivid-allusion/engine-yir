"""Identity constants. Standard library only.

The TUI imports this module, not ``engine.py``, so reading the provider's
display name never pulls in the provider's SDK.
"""

PROVIDER_NAME = "Yir"
PROVIDER_HOMEPAGE = "https://yir.ai"
PLATFORM = "yir"
API_KEY_ENV_VAR = "YIR_API_KEY"
API_KEY_PATTERN = r".+"
