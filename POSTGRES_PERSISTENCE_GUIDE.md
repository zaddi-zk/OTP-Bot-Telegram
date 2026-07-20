# PostgreSQL User Persistence - Complete Verification Guide

## ✅ System Architecture

The bot now uses **PostgreSQL as the single permanent data store** for all user information. Here's how it works:

### Data Flow

```
User Interaction → Bot Handler
    ↓
add_user_if_not_exists(user_id) → INSERT into PostgreSQL
    ↓
update_last_activity(user_id) → UPDATE last_activity in PostgreSQL
    ↓
User data PERSISTS across:
  - Bot restarts
  - Server redeployments
  - Railway process crashes
```

---

## 📊 What Gets Stored

When a user interacts with the bot, this data is **permanently saved in PostgreSQL**:

| Column | Example | Purpose |
|--------|---------|---------|
| user_id | 12345678 | Telegram user ID |
| is_premium | 1 or 0 | Premium status flag |
| subscription_end_date | 2026-08-20T10:00:00 | When subscription expires |
| created_at | 2026-07-20T10:00:00 | Account creation timestamp |
| last_activity | 2026-07-20T14:30:00 | Last interaction timestamp |
| role | "premium" or "free" | User role |
| notes | Optional notes | Admin notes |

---

## 🔄 How Users Are Created

### Step 1: User runs `/start`
```python
@bot.message_handler(commands=["start"])
def start_handler(message):
    user_id_str = str(message.from_user.id)
    
    # 🔑 CREATE or UPDATE user in PostgreSQL
    add_user_if_not_exists(user_id_str)      # INSERT new user
    update_last_activity(user_id_str)         # UPDATE timestamp
```

### Step 2: Data is committed to PostgreSQL
- `add_user_if_not_exists()` creates a new record with:
  - `is_premium = 0` (free user)
  - `role = "free"`
  - `created_at` = current timestamp
  - `last_activity` = current timestamp

### Step 3: Data persists permanently
- Even after bot restarts, the user record remains
- Subsequent commands update only `last_activity`
- Premium status upgrades update `is_premium` and `subscription_end_date`

---

## 👥 VIEW USERS Button Verification

When an admin clicks the **"👥 VIEW USERS"** button in the bot:

```python
if call.data == "open_view_users":
    # Query PostgreSQL for ALL users
    users = get_all_users_with_status()  # SELECT * FROM users
    free_count, premium_count = get_free_vs_premium_count()
    
    # Display results
    bot.send_message(chat_id, f"""
    👥 BOT USERS REPORT
    
    📊 Statistics:
      Total: {total}
      💎 Premium: {premium_count}
      📭 Free: {free_count}
    
    User List:
    {formatted_user_list}
    """)
```

### Expected Output (as users join):

```
👥 BOT USERS REPORT

📊 Statistics:
  Total: 5
  💎 Premium: 2
  📭 Free: 3

User List:
💎 12345678 — PREMIUM (Expires: 20/08/2026)
📭 87654321 — FREE
💎 11111111 — PREMIUM (Unlimited)
📭 22222222 — FREE
📭 33333333 — FREE
```

**Note:** Currently shows "No users found" because no users have interacted yet.

---

## ✅ Permanent Results Verification

### What Makes Results Permanent:

1. **SQLAlchemy Session Management**
   - Automatic transaction commit on success
   - Proper connection pooling

2. **PostgreSQL Guarantees**
   - ACID transactions
   - Data persists across connections
   - Supports concurrent access

3. **Connection Resilience**
   ```python
   _engine = create_engine(
       DATABASE_URL,
       pool_pre_ping=True,      # Validate connections
       pool_recycle=1800,       # Recycle stale connections
       pool_size=5,             # Connection pool size
       max_overflow=10,         # Overflow handling
   )
   ```

### Verification Steps (On Railway):

1. **First interaction**: User runs `/start`
   - Bot creates record in PostgreSQL ✓
   - Record has: user_id, is_premium=0, created_at, last_activity

2. **Admin checks users**: Click "👥 VIEW USERS"
   - PostgreSQL query returns all stored users
   - User appears in the list

3. **Promote to premium**: Admin runs `/approve user_id 30`
   - `set_user_premium(user_id, days=30)` runs
   - PostgreSQL updates: is_premium=1, subscription_end_date, role="premium"
   - UPDATE statement commits to database

4. **User activity updates**: User interacts again
   - `update_last_activity(user_id)` runs
   - PostgreSQL updates: last_activity = new_timestamp
   - Change persists permanently

---

## 🧪 Testing on Railway

To verify the persistence flow works:

### Setup
```bash
# 1. Set DATABASE_URL in Railway environment variables
DATABASE_URL = postgres://user:pass@host:port/dbname

# 2. Deploy bot to Railway
# 3. Run initialization
python scripts/create_users_table.py
python scripts/migrate_users_to_db.py
```

### Test Flow
```
1. User A: /start
   → Table shows: 1 FREE user

2. Admin: /approve user_a 30
   → Table shows: 1 PREMIUM user (expires 30 days)

3. User B: /start
   → Table shows: 1 PREMIUM + 1 FREE user

4. Bot restart (Railway auto-deploy)
   → All 2 users still in database ✓

5. Admin: /users (VIEW USERS)
   → Both users displayed with correct status ✓
```

---

## 📋 Key Functions for Persistence

| Function | What It Does | Permanent? |
|----------|-------------|-----------|
| `add_user_if_not_exists()` | INSERT new user | ✅ Yes |
| `update_last_activity()` | UPDATE timestamp | ✅ Yes |
| `set_user_premium()` | UPDATE subscription | ✅ Yes |
| `extend_subscription()` | ADD days to expiry | ✅ Yes |
| `get_all_users_with_status()` | SELECT all users | ✅ Reads from DB |
| `get_free_vs_premium_count()` | Get statistics | ✅ Reads from DB |
| `is_premium()` | Check subscription | ✅ Reads from DB |

---

## 🔐 Data Safety Guarantees

✅ **Survives bot restarts** - Data in PostgreSQL, not in memory  
✅ **Survives server crashes** - PostgreSQL is separate service  
✅ **Survives Railway deployments** - Database not affected  
✅ **Survives code changes** - Database persists independently  
✅ **Concurrent access safe** - Connection pooling + transactions  
✅ **Automatic backups** - Railway provides database backups  

---

## 🎯 Bottom Line

When users interact with the bot on Railway:
1. Every user is added to PostgreSQL
2. Every interaction updates their timestamp
3. Premium upgrades persist permanently
4. The VIEW USERS button shows accurate, persistent data
5. Nothing is lost on bot restarts

**The database is the single source of truth.**
