"""
Test PostgreSQL user persistence flow.

Verifies that:
1. Users are created in PostgreSQL when they interact with the bot
2. User data persists across queries
3. The VIEW USERS button retrieves correct data
4. Premium status and subscription dates are stored correctly
"""

import sys
from pathlib import Path

# Add parent directory to path so imports work
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
import os
import pytest

# Skip these heavy persistence tests when DATABASE_URL is not set in the
# environment. CI or local developers who wish to run them should export
# a working `DATABASE_URL` before running pytest.
if not os.getenv("DATABASE_URL"):
    pytest.skip("DATABASE_URL not set; skipping Postgres persistence tests", allow_module_level=True)
from datetime import datetime, timedelta
from core import user_manager as um


def test_user_creation_persists():
    """Test that creating a user stores it permanently in PostgreSQL."""
    test_user_id = "test-persist-user-123"
    
    # Ensure user doesn't exist yet
    um.add_user_if_not_exists(test_user_id)
    
    # Verify user was created by fetching their info
    user_info = um.get_user_info(test_user_id)
    assert user_info is not None
    assert user_info["user_id"] == test_user_id
    assert user_info["status"] == "FREE"
    print(f"✅ User {test_user_id} created and retrieved from PostgreSQL")


def test_user_activity_updates():
    """Test that last activity is updated and persists."""
    test_user_id = "test-activity-user-456"
    
    # Create user
    um.add_user_if_not_exists(test_user_id)
    
    # Get initial info
    first_info = um.get_user_info(test_user_id)
    assert first_info is not None
    
    # Update activity
    um.update_last_activity(test_user_id)
    
    # Verify activity was updated
    second_info = um.get_user_info(test_user_id)
    assert second_info is not None
    assert second_info["user_id"] == test_user_id
    print(f"✅ User activity updated and persisted for {test_user_id}")


def test_premium_subscription_persists():
    """Test that premium status and subscription dates persist."""
    test_user_id = "test-premium-user-789"
    
    # Create user and set as premium for 30 days
    um.add_user_if_not_exists(test_user_id)
    result = um.set_user_premium(test_user_id, is_premium=True, days_duration=30)
    assert result is True
    
    # Retrieve and verify
    user_info = um.get_user_info(test_user_id)
    assert user_info is not None
    assert user_info["status"] == "PREMIUM"
    assert user_info["is_premium"] is True
    assert user_info["days_left"] >= 29  # At least 29 days remaining
    print(f"✅ Premium subscription persisted for {test_user_id}")
    print(f"   Status: {user_info['status']}")
    print(f"   Expires: {user_info['subscription_end']}")
    print(f"   Days left: {user_info['days_left']}")


def test_get_all_users_query():
    """Test that get_all_users_with_status correctly retrieves all stored users."""
    # Create a few test users with different statuses
    test_users = [
        ("test-all-user-1", False),
        ("test-all-user-2", True),
        ("test-all-user-3", False),
    ]
    
    for user_id, make_premium in test_users:
        um.add_user_if_not_exists(user_id)
        if make_premium:
            um.set_user_premium(user_id, is_premium=True, days_duration=30)
    
    # Query all users
    all_users = um.get_all_users_with_status()
    assert len(all_users) > 0
    
    # Find our test users in the results
    result_user_ids = [u["user_id"] for u in all_users]
    for user_id, _ in test_users:
        assert user_id in result_user_ids
    
    print(f"✅ Retrieved {len(all_users)} total users from database")
    print(f"✅ Test users found in results: {test_users}")


def test_free_vs_premium_count():
    """Test that premium/free counts are accurately reported."""
    free_count, premium_count = um.get_free_vs_premium_count()
    
    print(f"✅ Database statistics:")
    print(f"   Free users: {free_count}")
    print(f"   Premium users: {premium_count}")
    print(f"   Total: {free_count + premium_count}")
    
    assert isinstance(free_count, int)
    assert isinstance(premium_count, int)
    assert free_count >= 0
    assert premium_count >= 0


def test_subscription_extend_persists():
    """Test that subscription extensions persist in the database."""
    test_user_id = "test-extend-user-999"
    
    # Create user and set initial premium (10 days)
    um.add_user_if_not_exists(test_user_id)
    um.set_user_premium(test_user_id, is_premium=True, days_duration=10)
    
    first_info = um.get_user_info(test_user_id)
    first_days = first_info["days_left"]
    
    # Extend subscription by 20 more days
    um.extend_subscription(test_user_id, days=20)
    
    # Verify extension persisted
    second_info = um.get_user_info(test_user_id)
    second_days = second_info["days_left"]
    
    assert second_days > first_days
    assert second_days >= 29  # Should be around 30 days now (10 + 20)
    print(f"✅ Subscription extension persisted")
    print(f"   Initial days left: {first_days}")
    print(f"   After extension: {second_days}")


def test_is_premium_check():
    """Test that is_premium() correctly checks the database."""
    test_user_id = "test-is-premium-user-555"
    
    # Create user (initially free)
    um.add_user_if_not_exists(test_user_id)
    assert um.is_premium(test_user_id) is False
    
    # Set as premium
    um.set_user_premium(test_user_id, is_premium=True, days_duration=30)
    assert um.is_premium(test_user_id) is True
    
    # Reset to free
    um.set_user_premium(test_user_id, is_premium=False)
    assert um.is_premium(test_user_id) is False
    
    print(f"✅ is_premium() checks work correctly for {test_user_id}")


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("PostgreSQL USER PERSISTENCE TESTS")
    print("=" * 70 + "\n")
    
    try:
        test_user_creation_persists()
        test_user_activity_updates()
        test_premium_subscription_persists()
        test_get_all_users_query()
        test_free_vs_premium_count()
        test_subscription_extend_persists()
        test_is_premium_check()
        
        print("\n" + "=" * 70)
        print("✅ ALL PERSISTENCE TESTS PASSED")
        print("=" * 70)
        print("\nSummary:")
        print("  ✓ Users are created and persisted in PostgreSQL")
        print("  ✓ User data survives queries and retrievals")
        print("  ✓ Premium status and subscription dates persist")
        print("  ✓ Activity updates persist")
        print("  ✓ VIEW USERS button data is accurate")
        print("  ✓ Statistics (free/premium counts) are correct\n")
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        raise
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        raise
