# User Persistence - Quick Verification Checklist

Use this checklist to verify that the PostgreSQL user persistence is working correctly on Railway.

---

## ✅ Pre-Deployment Verification (Local)

- [ ] `core/user_manager.py` exists with SQLAlchemy models and PostgreSQL functions
- [ ] `bot.py` imports `add_user_if_not_exists` and `update_last_activity` from user_manager
- [ ] `bot.py` line 6939-6940 calls these functions in `/start` handler
- [ ] `bot.py` line 5330 calls `get_all_users_with_status()` for VIEW USERS button
- [ ] `requirements.txt` includes `SQLAlchemy>=2.0.0`
- [ ] No syntax errors: `python -m py_compile core/user_manager.py bot.py`

---

## ✅ Deployment Verification (Railway)

### 1. Environment Setup
- [ ] `DATABASE_URL` is set in Railway environment variables
- [ ] Bot can start without "DATABASE_URL not configured" warning
- [ ] PostgreSQL connection is successful at startup

### 2. Schema Creation
- [ ] `users` table exists in Railway PostgreSQL console
- [ ] Table has columns: user_id, is_premium, subscription_end_date, created_at, last_activity, role, notes
- [ ] Indexes exist on is_premium and role columns

### 3. User Creation
- [ ] Open Telegram bot
- [ ] Send `/start` command
- [ ] Check Railway PostgreSQL console → users table
- [ ] Verify: Your user ID now appears in the table
- [ ] Verify: is_premium = 0 (free user)

### 4. Activity Updates
- [ ] Send another message to bot (any message)
- [ ] Check Railway PostgreSQL → users table → last_activity column
- [ ] Verify: last_activity timestamp has updated

### 5. View Users Button
- [ ] As bot owner/admin, open bot
- [ ] Click "👥 VIEW USERS" button in admin panel
- [ ] Verify: Shows list with your user ID
- [ ] Verify: Shows correct status "FREE" if not premium
- [ ] Verify: Shows statistics (Total, Premium, Free)

### 6. Premium Upgrade
- [ ] Admin runs: `/approve YOUR_USER_ID 30`
- [ ] Check Railway PostgreSQL → users table → your row
- [ ] Verify: is_premium = 1
- [ ] Verify: subscription_end_date ≈ 30 days from now
- [ ] Click "👥 VIEW USERS"
- [ ] Verify: Status shows "💎 PREMIUM (Expires: DD/MM/YYYY)"

### 7. Persistence After Restart
- [ ] Restart bot (or trigger Railway auto-deploy)
- [ ] Wait for bot to fully start
- [ ] Check Railway PostgreSQL console
- [ ] Verify: All users still in table (no data lost) ✓
- [ ] Verify: Premium status unchanged ✓
- [ ] Verify: Subscription end date unchanged ✓
- [ ] Click "👥 VIEW USERS"
- [ ] Verify: All users still displayed correctly ✓

### 8. Add More Users
- [ ] Have a different Telegram user send `/start` to bot
- [ ] Check Railway PostgreSQL → users table
- [ ] Verify: New user ID appears in table
- [ ] Click "👥 VIEW USERS"
- [ ] Verify: Both users displayed (Total: 2)

### 9. Statistics Accuracy
- [ ] Have 3+ users run `/start`
- [ ] Make some users premium using `/approve`
- [ ] Click "👥 VIEW USERS"
- [ ] Verify statistics match: Total = 3, Premium = (count), Free = (count)

---

## ❌ Troubleshooting

### Problem: VIEW USERS shows "No users found"
**Cause:** No users have run `/start` yet  
**Fix:** Have at least one user send `/start` to bot

### Problem: Database_URL not configured warning
**Cause:** Environment variable not set in Railway  
**Fix:** Add DATABASE_URL to Railway environment variables

### Problem: Users appear but disappear after restart
**Cause:** Data not actually in PostgreSQL (fallback mode)  
**Fix:** Verify DATABASE_URL is correct and PostgreSQL is reachable

### Problem: Premium status doesn't update
**Cause:** `set_user_premium()` not being called  
**Fix:** Verify `/approve` command is reaching the bot handler

### Problem: Can't see users table in Railway console
**Cause:** Wrong database selected or schema not created  
**Fix:** Check that bot is running (init_user_db() should create it), or manually run: `python scripts/create_users_table.py`

---

## 📊 What You Should See

### In Railway PostgreSQL Console (users table):
```
user_id         | is_premium | subscription_end_date        | created_at                   | last_activity
123456789       | 0          | NULL                         | 2026-07-20T10:00:00         | 2026-07-20T14:30:00
987654321       | 1          | 2026-08-20T10:00:00         | 2026-07-20T11:00:00         | 2026-07-20T12:00:00
```

### In Bot (👥 VIEW USERS button):
```
👥 BOT USERS REPORT

📊 Statistics:
  Total: 2
  💎 Premium: 1
  📭 Free: 1

User List:
💎 987654321 — PREMIUM (Expires: 20/08/2026)
📭 123456789 — FREE
```

---

## 🎯 Success Criteria

✅ All of the following should be TRUE:

1. Users created in PostgreSQL when they run `/start`
2. User data visible in Railway console
3. Timestamps update when users interact
4. Premium status persists when admin approves
5. Subscription end date calculated correctly
6. VIEW USERS button shows accurate list
7. Statistics match actual data
8. Data survives bot restart
9. Multiple users can be managed independently
10. No errors in logs related to database

---

## 📝 Once Verified

Once you've confirmed all items above, the system is ready for:
- ✅ Production use
- ✅ Scaling to thousands of users
- ✅ Multiple bot deployments
- ✅ Automatic backups (Railway handles this)
- ✅ Zero data loss guarantees
