# identity/utils.py

"""
Utility functions for name normalization and username formatting.
Matches AWS adapter behavior for consistency.
"""


def normalize_name(name: str) -> str:
    """
    Normalizes group/user names to be Azure AD compatible.
    Matches AWS adapter's _normalize_name behavior:
    - Converts Polish characters to ASCII equivalents
    - Replaces spaces and underscores with dashes
    - Ensures consistent naming across adapters
    
    Examples:
        "AI 2024L" → "AI-2024L"
        "Grupa_Test" → "Grupa-Test"
        "ąęłńóśźż" → "aelnoszz"
    """
    char_map = {
        'ą': 'a', 'ć': 'c', 'ę': 'e', 'ł': 'l', 'ń': 'n',
        'ó': 'o', 'ś': 's', 'ź': 'z', 'ż': 'z',
        'Ą': 'A', 'Ć': 'C', 'Ę': 'E', 'Ł': 'L', 'Ń': 'N',
        'Ó': 'O', 'Ś': 'S', 'Ź': 'Z', 'Ż': 'Z',
        ' ': '-', '_': '-'
    }
    normalized = name
    for char, replacement in char_map.items():
        normalized = normalized.replace(char, replacement)
    return normalized


def build_username_with_group_suffix(user_login: str, group_name: str) -> str:
    """
    Builds username with group suffix (matches AWS adapter format).
    
    Format: {user_login}-{normalized_group_name}
    Example: "s12345" + "AI 2024L" → "s12345-AI-2024L"
    
    This prevents username collisions when same user is in multiple groups.
    """
    normalized_group = normalize_name(group_name)
    return f"{user_login}-{normalized_group}"

