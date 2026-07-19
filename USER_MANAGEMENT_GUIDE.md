"""
ADMIN USER MANAGEMENT GUIDE
============================

This guide explains how to use the new user database system to manage 
free and premium users, approve subscriptions, and view user statistics.

═══════════════════════════════════════════════════════════════════════════

1. VIEWING ALL USERS (NEW FEATURE)
─────────────────────────────────

Location: KEY ADMIN → 👥 VIEW USERS

Shows:
  • Total users count
  • Premium users count
  • Free users count  
  • User list with status (💎 PREMIUM, 📭 FREE, ⏱️ EXPIRED)
  • Subscription end dates for each premium user

This gives you complete visibility into your user base at a glance.

═══════════════════════════════════════════════════════════════════════════

2. APPROVING USERS FOR PREMIUM (NEW FEATURE)
────────────────────────────────────────────

Location: KEY ADMIN → 👤 Approve Premium

Steps:
  1. Click "Approve Premium" button
  2. Send the user ID (e.g., 123456789)
  3. Select subscription duration:
     • 1 Day
     • 3 Days
     • 7 Days
     • 30 Days
     • 90 Days
     • Lifetime

After approval:
  ✅ User is immediately set as premium in the database
  ✅ Subscription end date is calculated and stored
  ✅ Admin receives confirmation with expiry date
  ✅ User receives notification (if bot can reach them)
  ✅ User sees "PREMIUM" status in their main menu on next visit

═══════════════════════════════════════════════════════════════════════════

3. USER STATUS IN MAIN MENU (FIXED)
──────────────────────────────────

Users now see ACCURATE information:

FREE USER:
  🛡️ Role: FREE USER
  💸 Plan: FREE
  ⏳ Subscription: No active subscription
  ⚡ Free calls remaining: 3/5

PREMIUM USER (shows real expiry date):
  🛡️ Role: PREMIUM USER
  💎 Plan: PREMIUM
  ⏳ Subscription: Active until 18/08/2026  ← REAL DATE FROM DATABASE
  ⚡ Free calls: Unlimited

ADMIN/OWNER:
  🛡️ Role: ADMIN OWNER
  💎 Plan: PREMIUM
  ⏳ Subscription: Unlimited
  ⚡ Free calls: Unlimited

═══════════════════════════════════════════════════════════════════════════

4. DATABASE DETAILS
──────────────────

Database Location: conf/users.db (SQLite)

Stored Information for each user:
  • user_id: Telegram user ID
  • is_premium: Boolean (0=free, 1=premium)
  • subscription_end_date: ISO format datetime or NULL for unlimited
  • created_at: When user first joined
  • last_activity: Last time user interacted with bot
  • role: 'free', 'premium', 'admin', 'developer', 'owner'
  • notes: Admin notes (optional)

This is PERSISTENT and NOT affected by server restarts.

═══════════════════════════════════════════════════════════════════════════

5. MANAGING EXPIRED SUBSCRIPTIONS (AUTOMATIC)
─────────────────────────────────────────────

Every time you run: get_expired_premium_users() or reset_expired_subscriptions()

Expired users are automatically reset to FREE status.

Example usage in admin panel:
  You can add a button to run reset_expired_subscriptions()
  to clean up expired accounts.

═══════════════════════════════════════════════════════════════════════════

6. EXTENDING SUBSCRIPTIONS
──────────────────────────

If a user asks for more time, use extend_subscription():

  from core.user_manager import extend_subscription
  extend_subscription(user_id, days=30)  # Add 30 more days

This adds to their existing subscription end date.

═══════════════════════════════════════════════════════════════════════════

7. TROUBLESHOOTING
──────────────────

❓ User still sees "FREE" after approval?
   → Bot needs restart for changes to take effect
   → Or user needs to send /start to refresh cache

❓ Subscription dates look wrong?
   → Check conf/users.db is being used (check timestamps)
   → Verify system time is correct on server

❓ User was approved but can't use premium features?
   → Check subscription_end_date is in future
   → Run check_subscription(user_id) in bot code
   → May need to restart bot to clear any cached data

═══════════════════════════════════════════════════════════════════════════

8. ADMIN API (FOR DEVELOPERS)
─────────────────────────────

All functions in core/user_manager.py:

  init_user_db()
    Initialize database (called automatically)

  add_user_if_not_exists(user_id)
    Track user in database

  set_user_premium(user_id, is_premium=True, days_duration=30)
    Set user as premium with duration

  extend_subscription(user_id, days=30)
    Add days to existing subscription

  is_premium(user_id) → bool
    Check if user is currently premium

  get_subscription_end_date(user_id) → str
    Get formatted expiry date (DD/MM/YYYY)

  get_all_users_with_status() → List[Dict]
    Get all users with their status

  get_free_vs_premium_count() → (int, int)
    Get count of free and premium users

  get_expired_premium_users() → List[str]
    Get users whose subscription expired

  reset_expired_subscriptions() → int
    Reset expired users to free (returns count)

═══════════════════════════════════════════════════════════════════════════

SUMMARY OF FIXES
─────────────────

✅ Database now persists user data across restarts
✅ Users see real subscription end dates in menu
✅ Admin can approve premium with custom durations
✅ Automatic expiration tracking
✅ View all users with their status at a glance
✅ No more confusion between free and premium users
✅ Subscription dates are accurate and stored safely

═══════════════════════════════════════════════════════════════════════════
"""
