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


def make_mail_nickname(base_username: str) -> str:
    """
    Generates mailNickname compliant with Azure AD requirements.
    
    Requirements:
    - Length: 1-64 characters
    - Allowed characters: alphanumeric, hyphens, underscores
    - Must be lowercase
    
    If base_username exceeds 64 chars, truncates and adds hash suffix for uniqueness.
    
    Args:
        base_username: Base username (may include group suffix)
    
    Returns:
        Valid mailNickname (1-64 chars, lowercase, sanitized)
    """
    import hashlib
    import re
    
    # Sanitize: keep only alphanumeric, hyphens, underscores
    sanitized = re.sub(r'[^a-zA-Z0-9_-]', '', base_username)
    
    # Convert to lowercase
    sanitized = sanitized.lower()
    
    # Azure AD limit: 64 characters
    MAX_LENGTH = 64
    
    if len(sanitized) <= MAX_LENGTH:
        if not sanitized:
            # Fallback if sanitization removed everything
            sanitized = "user"
        return sanitized
    
    # Truncate and add hash suffix for uniqueness
    # Use first 8 chars of hash (gives good uniqueness)
    hash_suffix = hashlib.md5(base_username.encode()).hexdigest()[:8]
    
    # Reserve space for hash: 8 chars + 1 hyphen = 9 chars
    max_base_length = MAX_LENGTH - 9
    
    # Truncate base and append hash
    truncated_base = sanitized[:max_base_length]
    result = f"{truncated_base}-{hash_suffix}"
    
    # Final check (should always be <= 64 now)
    if len(result) > MAX_LENGTH:
        result = result[:MAX_LENGTH]
    
    return result


def make_upn_local_part(full_username: str) -> str:
    """
    Generates UPN local part (part before @) compliant with Azure AD requirements.
    
    Requirements:
    - Length: 1-64 characters (before @)
    - Allowed characters: alphanumeric, hyphens, underscores, dots
    - Must be lowercase
    
    If full_username exceeds 64 chars, truncates and adds hash suffix for uniqueness.
    Preserves AWS adapter format (user_login-group_name) but ensures Azure AD compliance.
    
    Args:
        full_username: Full username with group suffix (e.g., "s12345-AI-2024L")
    
    Returns:
        Valid UPN local part (1-64 chars, lowercase, sanitized)
    """
    import hashlib
    import re
    
    # Sanitize: keep only alphanumeric, hyphens, underscores, dots
    # UPN allows dots, unlike mailNickname
    sanitized = re.sub(r'[^a-zA-Z0-9_.-]', '', full_username)
    
    # Convert to lowercase
    sanitized = sanitized.lower()
    
    # Azure AD limit: 64 characters for local part
    MAX_LENGTH = 64
    
    if len(sanitized) <= MAX_LENGTH:
        if not sanitized:
            # Fallback if sanitization removed everything
            sanitized = "user"
        return sanitized
    
    # Truncate and add hash suffix for uniqueness
    # Use first 8 chars of hash (gives good uniqueness)
    hash_suffix = hashlib.md5(full_username.encode()).hexdigest()[:8]
    
    # Reserve space for hash: 8 chars + 1 hyphen = 9 chars
    max_base_length = MAX_LENGTH - 9
    
    # Truncate base and append hash
    truncated_base = sanitized[:max_base_length]
    result = f"{truncated_base}-{hash_suffix}"
    
    # Final check (should always be <= 64 now)
    if len(result) > MAX_LENGTH:
        result = result[:MAX_LENGTH]
    
    return result

