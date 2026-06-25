# core/crypto.py
"""
Encryption utilities for OTP-Bot-Telegram.
Provides AES-256 encryption for sensitive configuration files.
Uses Fernet (symmetric encryption) with key derivation from environment variable.
"""
import os
import json
import base64
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

logger = logging.getLogger("OTP-Bot.crypto")

# ======================================================================
# Key management
# ======================================================================
def generate_encryption_key(salt: bytes = None) -> str:
    """
    Generate a new Fernet encryption key.
    
    Args:
        salt: Optional salt bytes (if not provided, random salt is generated)
    
    Returns:
        Base64-encoded encryption key
    """
    if salt is None:
        salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(os.urandom(32)))
    return key.decode()

def load_encryption_key() -> Optional[str]:
    """
    Load encryption key from environment variable.
    
    Returns:
        Encryption key as string, or None if not set
    """
    key = os.getenv("CONFIG_ENCRYPTION_KEY")
    if key:
        return key
    logger.warning("CONFIG_ENCRYPTION_KEY not set in environment")
    return None

def create_encryption_key_file(key_path: Path = Path("conf/encryption.key")) -> bool:
    """
    Create a new encryption key file (for initial setup).
    
    Args:
        key_path: Path to save the key
    
    Returns:
        True if successful, False otherwise
    """
    try:
        key = generate_encryption_key()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_text(key, encoding="utf-8")
        logger.info(f"Encryption key saved to {key_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to create encryption key: {e}")
        return False

# ======================================================================
# Fernet cipher instance
# ======================================================================
def get_cipher() -> Optional[Fernet]:
    """
    Get a Fernet cipher instance using the encryption key.
    
    Returns:
        Fernet object or None if key not available
    """
    key = load_encryption_key()
    if not key:
        return None
    try:
        return Fernet(key.encode())
    except Exception as e:
        logger.error(f"Invalid encryption key: {e}")
        return None

# ======================================================================
# File encryption/decryption
# ======================================================================
def encrypt_file(file_path: Path, output_path: Optional[Path] = None) -> bool:
    """
    Encrypt a file and save to output path (or same path with .enc extension).
    
    Args:
        file_path: Path to the file to encrypt
        output_path: Optional output path (if None, uses file_path with .enc)
    
    Returns:
        True if successful, False otherwise
    """
    cipher = get_cipher()
    if not cipher:
        logger.error("Cannot encrypt: no encryption key available")
        return False
    
    try:
        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return False
        
        # Read plaintext file
        with open(file_path, "rb") as f:
            data = f.read()
        
        # Encrypt
        encrypted = cipher.encrypt(data)
        
        # Determine output path
        if output_path is None:
            output_path = file_path.with_suffix(file_path.suffix + ".enc")
        
        # Write encrypted data
        with open(output_path, "wb") as f:
            f.write(encrypted)
        
        logger.info(f"Encrypted {file_path} -> {output_path}")
        return True
    except Exception as e:
        logger.error(f"Encryption failed: {e}")
        return False

def decrypt_file(encrypted_path: Path, output_path: Optional[Path] = None) -> bool:
    """
    Decrypt an encrypted file and save to output path.
    
    Args:
        encrypted_path: Path to the encrypted file
        output_path: Optional output path (if None, strips .enc extension)
    
    Returns:
        True if successful, False otherwise
    """
    cipher = get_cipher()
    if not cipher:
        logger.error("Cannot decrypt: no encryption key available")
        return False
    
    try:
        if not encrypted_path.exists():
            logger.error(f"Encrypted file not found: {encrypted_path}")
            return False
        
        # Read encrypted data
        with open(encrypted_path, "rb") as f:
            encrypted = f.read()
        
        # Decrypt
        decrypted = cipher.decrypt(encrypted)
        
        # Determine output path
        if output_path is None:
            if encrypted_path.suffix == ".enc":
                output_path = encrypted_path.with_suffix("")
            else:
                output_path = encrypted_path.with_name(encrypted_path.name + ".dec")
        
        # Write decrypted data
        with open(output_path, "wb") as f:
            f.write(decrypted)
        
        logger.info(f"Decrypted {encrypted_path} -> {output_path}")
        return True
    except Exception as e:
        logger.error(f"Decryption failed: {e}")
        return False

# ======================================================================
# JSON file encryption/decryption
# ======================================================================
def encrypt_json(data: Dict[str, Any], file_path: Path) -> bool:
    """
    Encrypt a dictionary and save as JSON to the specified path.
    
    Args:
        data: Dictionary to encrypt
        file_path: Output path (will be saved with .enc extension)
    
    Returns:
        True if successful, False otherwise
    """
    cipher = get_cipher()
    if not cipher:
        logger.error("Cannot encrypt JSON: no encryption key available")
        return False
    
    try:
        # Convert to JSON bytes
        json_bytes = json.dumps(data, indent=2).encode("utf-8")
        
        # Encrypt
        encrypted = cipher.encrypt(json_bytes)
        
        # Ensure parent directory exists
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write encrypted data
        enc_path = file_path.with_suffix(file_path.suffix + ".enc")
        with open(enc_path, "wb") as f:
            f.write(encrypted)
        
        logger.info(f"Encrypted JSON saved to {enc_path}")
        return True
    except Exception as e:
        logger.error(f"JSON encryption failed: {e}")
        return False

def decrypt_json(file_path: Path) -> Optional[Dict[str, Any]]:
    """
    Decrypt a JSON file and return the dictionary.
    
    Args:
        file_path: Path to the encrypted JSON file (should end with .enc)
    
    Returns:
        Decrypted dictionary, or None if decryption fails
    """
    cipher = get_cipher()
    if not cipher:
        logger.error("Cannot decrypt JSON: no encryption key available")
        return None
    
    try:
        if not file_path.exists():
            logger.error(f"Encrypted JSON file not found: {file_path}")
            return None
        
        # Read encrypted data
        with open(file_path, "rb") as f:
            encrypted = f.read()
        
        # Decrypt
        decrypted = cipher.decrypt(encrypted)
        
        # Parse JSON
        data = json.loads(decrypted.decode("utf-8"))
        logger.info(f"Decrypted JSON from {file_path}")
        return data
    except Exception as e:
        logger.error(f"JSON decryption failed: {e}")
        return None

# ======================================================================
# Config file encryption (settings.txt)
# ======================================================================
def encrypt_settings_file(settings_path: Path = Path("conf/settings.txt")) -> bool:
    """
    Encrypt the settings.txt file.
    
    Args:
        settings_path: Path to settings.txt
    
    Returns:
        True if successful, False otherwise
    """
    try:
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = json.load(f)
        return encrypt_json(settings, settings_path)
    except Exception as e:
        logger.error(f"Failed to encrypt settings: {e}")
        return False

def decrypt_settings_file(settings_enc_path: Path = Path("conf/settings.txt.enc")) -> Optional[Dict[str, Any]]:
    """
    Decrypt the encrypted settings file.
    
    Args:
        settings_enc_path: Path to settings.txt.enc
    
    Returns:
        Decrypted settings dictionary, or None if decryption fails
    """
    return decrypt_json(settings_enc_path)

# ======================================================================
# Premium keys encryption
# ======================================================================
def encrypt_premium_keys(keys_path: Path = Path("conf/premium_keys.json")) -> bool:
    """
    Encrypt the premium_keys.json file.
    
    Args:
        keys_path: Path to premium_keys.json
    
    Returns:
        True if successful, False otherwise
    """
    try:
        with open(keys_path, "r", encoding="utf-8") as f:
            keys = json.load(f)
        return encrypt_json(keys, keys_path)
    except Exception as e:
        logger.error(f"Failed to encrypt premium keys: {e}")
        return False

def decrypt_premium_keys(keys_enc_path: Path = Path("conf/premium_keys.json.enc")) -> Optional[Dict[str, Any]]:
    """
    Decrypt the encrypted premium keys file.
    
    Args:
        keys_enc_path: Path to premium_keys.json.enc
    
    Returns:
        Decrypted premium keys dictionary, or None if decryption fails
    """
    return decrypt_json(keys_enc_path)

# ======================================================================
# Auto‑encryption on save (hook into config and premium modules)
# ======================================================================
def save_encrypted_config(config_dict: Dict[str, Any], config_path: Path = Path("conf/settings.txt")) -> None:
    """
    Save configuration dictionary and automatically encrypt it.
    
    Args:
        config_dict: Configuration dictionary
        config_path: Path to save (plaintext for compatibility, but also creates encrypted copy)
    """
    # Save plaintext (for backward compatibility)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_dict, f, indent=2)
    
    # Encrypt and save encrypted version
    encrypt_json(config_dict, config_path)
    logger.info("Configuration saved and encrypted")

def load_encrypted_config(config_path: Path = Path("conf/settings.txt")) -> Dict[str, Any]:
    """
    Load configuration from encrypted file (fallback to plaintext if encrypted not found).
    
    Args:
        config_path: Path to configuration file
    
    Returns:
        Configuration dictionary
    """
    # Try encrypted version first
    enc_path = config_path.with_suffix(config_path.suffix + ".enc")
    if enc_path.exists():
        data = decrypt_json(enc_path)
        if data is not None:
            return data
    
    # Fallback to plaintext
    if config_path.exists():
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    
    return {}

# ======================================================================
# Example usage (comment out when importing)
# ======================================================================
if __name__ == "__main__":
    # Test key generation
    key = generate_encryption_key()
    print(f"Generated key: {key[:20]}...")
    
    # Test encryption/decryption
    test_data = {"test": "Hello World", "number": 42}
    test_path = Path("conf/test.json")
    test_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Encrypt
    encrypt_json(test_data, test_path)
    enc_path = test_path.with_suffix(test_path.suffix + ".enc")
    print(f"Encrypted file: {enc_path.exists()}")
    
    # Decrypt
    decrypted = decrypt_json(enc_path)
    print(f"Decrypted data: {decrypted}")
    
    # Cleanup
    test_path.unlink(missing_ok=True)
    enc_path.unlink(missing_ok=True)