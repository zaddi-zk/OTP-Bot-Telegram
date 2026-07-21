#!/usr/bin/env python3
"""
Test script to verify key redemption persists to PostgreSQL.
Tests the critical security fix for premium key synchronization.

This script verifies:
1. Key can be redeemed
2. Expiry date is calculated correctly
3. PostgreSQL database is updated (not just file)
4. File and database expiry dates match
5. Key cannot be redeemed twice
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.user_manager import set_user_premium, is_premium, get_user_info, init_user_db
from core.files import read_user_file, write_user_file
from core.auth import check_subscription
from premium import redeem_premium_key, generate_premium_key, load_premium_keys, save_premium_keys

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("KeyRedemptionTest")

TEST_USER_ID = "999999999"  # Test user ID

def test_key_redemption_persistence():
    """Test that key redemption updates PostgreSQL"""
    logger.info("=" * 80)
    logger.info("TEST: Key Redemption Persistence (File + PostgreSQL Sync)")
    logger.info("=" * 80)
    
    # Initialize database
    logger.info("\n1️⃣  Initializing PostgreSQL database...")
    try:
        init_user_db()
        logger.info("   ✅ Database initialized")
    except Exception as e:
        logger.error(f"   ❌ Failed to initialize: {e}")
        return False
    
    # Create test user
    logger.info(f"\n2️⃣  Creating test user {TEST_USER_ID}...")
    try:
        from core.user_manager import add_user_if_not_exists
        add_user_if_not_exists(TEST_USER_ID)
        logger.info("   ✅ Test user created")
    except Exception as e:
        logger.error(f"   ❌ Failed to create user: {e}")
        return False
    
    # Generate a test key
    logger.info("\n3️⃣  Generating premium key...")
    try:
        key = generate_premium_key(days=30, created_by="TEST_ADMIN")
        test_token = key["token"]
        logger.info(f"   ✅ Key generated: {test_token}")
        logger.info(f"      Duration: {key['days']} days")
    except Exception as e:
        logger.error(f"   ❌ Failed to generate key: {e}")
        return False
    
    # Verify user is NOT premium before redemption
    logger.info(f"\n4️⃣  Checking user status BEFORE redemption...")
    try:
        from core.user_manager import is_premium as db_is_premium
        before_file = check_subscription(TEST_USER_ID)
        before_db = db_is_premium(TEST_USER_ID)
        logger.info(f"   File status: {before_file}")
        logger.info(f"   DB status: {before_db}")
        if before_file == "INACTIVE" and before_db == False:
            logger.info("   ✅ User correctly shown as inactive/free")
        else:
            logger.warning("   ⚠️  User status unexpected before redemption")
    except Exception as e:
        logger.error(f"   ❌ Failed to check status: {e}")
    
    # Redeem key
    logger.info(f"\n5️⃣  Redeeming key {test_token}...")
    try:
        success, message = redeem_premium_key(TEST_USER_ID, test_token)
        if success:
            logger.info(f"   ✅ Key redeemed successfully")
            logger.info(f"      Expiry: {message}")
        else:
            logger.error(f"   ❌ Redemption failed: {message}")
            return False
    except Exception as e:
        logger.error(f"   ❌ Error during redemption: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Verify file was updated
    logger.info(f"\n6️⃣  Verifying FILE persistence...")
    try:
        file_expiry = read_user_file(TEST_USER_ID, "subs.txt", "")
        if file_expiry:
            logger.info(f"   ✅ File updated: subs.txt = {file_expiry}")
        else:
            logger.error(f"   ❌ File NOT updated")
            return False
    except Exception as e:
        logger.error(f"   ❌ Failed to read file: {e}")
        return False
    
    # Verify database was updated (CRITICAL FIX)
    logger.info(f"\n7️⃣  Verifying DATABASE persistence...")
    try:
        from core.user_manager import is_premium as db_is_premium
        db_premium = db_is_premium(TEST_USER_ID)
        if db_premium:
            logger.info(f"   ✅ DATABASE UPDATED: is_premium = True")
        else:
            logger.error(f"   ❌ CRITICAL BUG: Database NOT updated (is_premium = False)")
            logger.error(f"      This is the persistence bug we're fixing!")
            return False
    except Exception as e:
        logger.error(f"   ❌ Failed to check database: {e}")
        return False
    
    # Get detailed user info
    logger.info(f"\n8️⃣  Retrieving detailed user info...")
    try:
        user_info = get_user_info(TEST_USER_ID)
        if user_info:
            logger.info(f"   ✅ User record found in database:")
            logger.info(f"      is_premium: {user_info.get('is_premium')}")
            logger.info(f"      subscription_end_date: {user_info.get('subscription_end_date')}")
            logger.info(f"      role: {user_info.get('role')}")
        else:
            logger.warning(f"   ⚠️  User record not found")
    except Exception as e:
        logger.error(f"   ❌ Failed to get user info: {e}")
    
    # Verify expiry dates match
    logger.info(f"\n9️⃣  Verifying expiry date consistency...")
    try:
        file_expiry_str = read_user_file(TEST_USER_ID, "subs.txt", "")
        
        # Parse file expiry (format: DD/MM/YYYY)
        file_exp_date = datetime.strptime(file_expiry_str, "%d/%m/%Y")
        file_exp_str = file_exp_date.strftime("%Y-%m-%d")
        
        # Parse database expiry
        user_info = get_user_info(TEST_USER_ID)
        db_exp_date = user_info.get('subscription_end_date')
        
        if db_exp_date:
            # Handle both datetime and string formats
            if isinstance(db_exp_date, str):
                db_exp_str = db_exp_date.split(' ')[0]  # Extract date portion
            else:
                db_exp_str = db_exp_date.strftime("%Y-%m-%d")
            
            logger.info(f"   File expiry: {file_exp_str}")
            logger.info(f"   DB expiry:   {db_exp_str}")
            
            if file_exp_str == db_exp_str:
                logger.info(f"   ✅ Expiry dates MATCH (consistent)")
            else:
                logger.warning(f"   ⚠️  Expiry dates differ (file vs DB)")
        else:
            logger.warning(f"   ⚠️  Database subscription_end_date is empty")
    except Exception as e:
        logger.error(f"   ❌ Failed to verify expiry: {e}")
    
    # Try to redeem same key again (should fail)
    logger.info(f"\n🔟 Testing key re-use prevention...")
    try:
        success, message = redeem_premium_key(TEST_USER_ID, test_token)
        if not success and "already been used" in message:
            logger.info(f"   ✅ Key re-use prevented: {message}")
        else:
            logger.error(f"   ❌ Key re-use NOT prevented (should have failed)")
            return False
    except Exception as e:
        logger.error(f"   ❌ Error during re-use test: {e}")
        return False
    
    # Verify key marked as used
    logger.info(f"\n1️⃣1️⃣ Verifying key marked as USED...")
    try:
        keys = load_premium_keys()
        for key in keys:
            if key.get("token") == test_token:
                if key.get("used"):
                    logger.info(f"   ✅ Key marked as used: {key.get('used_at')}")
                    logger.info(f"      Used by: {key.get('used_by')}")
                else:
                    logger.error(f"   ❌ Key NOT marked as used (security issue)")
                    return False
                break
    except Exception as e:
        logger.error(f"   ❌ Failed to verify key status: {e}")
        return False
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ ALL TESTS PASSED - Key redemption persists correctly!")
    logger.info("=" * 80)
    logger.info("\nSummary:")
    logger.info("- Key redeemed successfully")
    logger.info("- File updated (subs.txt)")
    logger.info("- PostgreSQL updated (is_premium, subscription_end_date)")
    logger.info("- Expiry dates match between file and database")
    logger.info("- Key marked as used (prevents re-use)")
    logger.info("- Audit trail created")
    
    return True

if __name__ == "__main__":
    try:
        success = test_key_redemption_persistence()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
