# tests/test_https_validation.py

"""
Testy jednostkowe dla walidacji HTTPS w Azure adapterze.
"""

import pytest
from azure_clients import _validate_https_url, _validate_scope


class TestHTTPSValidation:
    """Testy walidacji HTTPS URL."""
    
    def test_validate_https_url_accepts_https(self):
        """Test że _validate_https_url akceptuje https:// URLs."""
        # Should not raise
        _validate_https_url("https://management.azure.com")
        _validate_https_url("https://example.com/path")
        _validate_https_url("https://subdomain.example.com:443/api")
    
    def test_validate_https_url_rejects_http(self):
        """Test że _validate_https_url rzuca ValueError dla http:// URLs."""
        with pytest.raises(ValueError, match="must use HTTPS"):
            _validate_https_url("http://management.azure.com")
        
        with pytest.raises(ValueError, match="must use HTTPS"):
            _validate_https_url("http://example.com")
    
    def test_validate_https_url_rejects_no_scheme(self):
        """Test że _validate_https_url rzuca ValueError dla URL bez schematu."""
        with pytest.raises(ValueError, match="must use HTTPS"):
            _validate_https_url("management.azure.com")
        
        with pytest.raises(ValueError, match="must use HTTPS"):
            _validate_https_url("/subscriptions/123")


class TestScopeValidation:
    """Testy walidacji scope."""
    
    def test_validate_scope_accepts_valid_scope(self):
        """Test że _validate_scope akceptuje prawidłowe scope."""
        # Should not raise
        _validate_scope("/subscriptions/12345678-1234-1234-1234-123456789012")
        _validate_scope("/subscriptions/123/resourceGroups/rg-name")
    
    def test_validate_scope_rejects_invalid_format(self):
        """Test że _validate_scope rzuca ValueError dla nieprawidłowego formatu."""
        with pytest.raises(ValueError, match="must start with '/subscriptions/'"):
            _validate_scope("subscriptions/123")
        
        with pytest.raises(ValueError, match="must start with '/subscriptions/'"):
            _validate_scope("http://management.azure.com/subscriptions/123")
    
    def test_validate_scope_rejects_http(self):
        """Test że _validate_scope rzuca ValueError jeśli scope zawiera http://."""
        with pytest.raises(ValueError, match="must not contain http://"):
            _validate_scope("/subscriptions/123/http://example.com")
        
        with pytest.raises(ValueError, match="must not contain http://"):
            _validate_scope("http://management.azure.com/subscriptions/123")
