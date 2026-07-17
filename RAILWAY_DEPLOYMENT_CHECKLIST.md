# ✅ DEPLOYMENT CHECKLIST - OTP BOT TO RAILWAY

## 🎯 Pre-Deployment (Local)

- [x] Code pushed to GitHub (main branch)
- [x] All features tested locally
- [x] `.env.example` created with all required variables
- [x] `requirements.txt` includes all dependencies
- [x] `railway.toml` configured with build & start commands
- [x] Preflight check script added (`railway_preflight.py`)
- [x] Graceful shutdown handlers added to `bot.py`
- [x] Startup banner added for visibility
- [x] Health check endpoints working (`/health`, FastAPI health)

---

## 🚀 Railway Setup

### Step 1: Connect GitHub Repository
- [ ] Go to https://railway.app
- [ ] Create new project
- [ ] Select "Deploy from GitHub"
- [ ] Authenticate with GitHub
- [ ] Select `OTP-Bot-Telegram-clean` repo
- [ ] Select `main` branch
- [ ] Click "Deploy"
- **Status:** Watch the build log, should complete in 2-3 minutes

### Step 2: Set Critical Environment Variables
Navigate to **Project → Settings → Variables** and add:

#### Telegram Bot (Required)
- [ ] `BOT_TOKEN` = Your token from @BotFather
- [ ] `USE_WEBHOOK` = `false` (polling is more reliable on Railway)

#### Twilio Integration (Required for calls)
- [ ] `TWILIO_ACCOUNT_SID` = Your SID (starts with AC)
- [ ] `TWILIO_AUTH_TOKEN` = Your auth token (64 chars)
- [ ] `TWILIO_PHONE_NUMBER` = Your Twilio number (+1...)
- [ ] `NGROK_URL` = Your webhook URL (see below)

#### Webhook URL Setup
Choose ONE:

**Option A: Use ngrok (external)**
- [ ] Install ngrok: https://ngrok.com
- [ ] Run: `ngrok http 5000`
- [ ] Copy HTTPS URL: `https://abc123.ngrok-free.dev`
- [ ] Set `NGROK_URL` = this URL
- [ ] In Twilio console, set webhooks to `{NGROK_URL}/voice` and `{NGROK_URL}/twilio/status`

**Option B: Use Railway domain (recommended)**
- [ ] Get your Railway domain from deployment URL
- [ ] Set `NGROK_URL` = `https://your-otp-bot-production.up.railway.app`
- [ ] In Twilio console, set webhooks to same domain + endpoints

#### Telegram Channels (Optional but recommended)
- [ ] `MAIN_CHANNEL_URL` = Your channel URL
- [ ] `MAIN_CHANNEL_ID` = `@channel_username` or numeric ID
- [ ] `BACKUP_CHANNEL_URL` = Backup channel URL
- [ ] `BACKUP_CHANNEL_ID` = Backup channel ID

#### Admin Access
- [ ] `OWNER_ID` = Your Telegram user ID
- [ ] `ADMIN_ID` = Admin user ID (if different)
- [ ] `DEVELOPER_IDS` = Comma-separated IDs

#### Voice Synthesis (ElevenLabs - Optional)
- [ ] `ELEVENLABS_API_KEY` = Your API key
- [ ] `DEFAULT_ELEVENLABS_VOICE_ID` = A voice ID (get from dashboard)
- [ ] `ELEVENLABS_MODEL` = `eleven_turbo_v2`

#### Payment Wallets (Optional)
- [ ] `PAYMENT_BTC` = Your BTC wallet address
- [ ] `PAYMENT_ETH` = Your ETH wallet address
- [ ] `PAYMENT_USDT` = Your USDT wallet address
- [ ] `PAYMENT_LTC` = Your LTC wallet address

#### Servers (Auto-set, but verify)
- [ ] `PORT` = `5000` (Railway sets this)
- [ ] `FLASK_PORT` = `5000`
- [ ] `FASTAPI_PORT` = `5001`
- [ ] `DEBUG` = `false`

---

## 🔍 Verification Checklist

### Build Verification
- [ ] Build log shows "✅ Build successful"
- [ ] No ModuleNotFoundError in build log
- [ ] Build completed in < 5 minutes

### Runtime Verification
- [ ] Service is "Running" (green status in Railway)
- [ ] Logs show "🚀 HOTTBOIIHITZZ PREMIUM OTP BOT v4.1 STARTED"
- [ ] Logs show "Starting application in full mode"
- [ ] Logs show "Flask server started on 0.0.0.0:5000"
- [ ] Logs show "FastAPI server started on 0.0.0.0:5001"
- [ ] Logs show "Telegram polling active"
- [ ] No Python exceptions in logs

### Health Check
- [ ] Visit `https://your-domain.up.railway.app/health`
- [ ] Returns: `{"status":"ok"}` (or similar)
- [ ] HTTP 200 response code

### Feature Testing

**Telegram Bot**
- [ ] Send `/start` to bot on Telegram
- [ ] Bot responds with menu
- [ ] Logs show message processing
- [ ] Can execute bot commands

**Twilio Calls** (if enabled)
- [ ] Initiate a test call from bot
- [ ] Twilio receives webhook
- [ ] Call connects and plays audio
- [ ] Call recording captured
- [ ] Logs show call events

**Voice Synthesis** (if ElevenLabs configured)
- [ ] Make a call with voice enabled
- [ ] Hear synthesized voice (not robotic)
- [ ] Voice quality is acceptable

**Live Listen** (if using WebSocket monitoring)
- [ ] Access live.html endpoint
- [ ] Can monitor active calls
- [ ] Real-time audio streaming works

**Scheduled Calls** (if configured)
- [ ] Create a scheduled call
- [ ] Scheduler executes at right time
- [ ] Call is made automatically
- [ ] Logs show scheduler running

---

## 🚨 Troubleshooting During Deployment

### Build Fails
| Error | Solution |
|-------|----------|
| ModuleNotFoundError | Check all imports in bot.py are in requirements.txt |
| "command not found: python" | Check railway.toml uses correct Python |
| SyntaxError in bot.py | Run `python -m py_compile bot.py` locally |

### Runtime Fails
| Error | Solution |
|-------|----------|
| "Cannot bind to port 5000" | Check PORT variable, Railway will assign one |
| "BOT_TOKEN not configured" | Verify BOT_TOKEN is set in Variables |
| "Twilio auth failed" | Verify TWILIO_ACCOUNT_SID and AUTH_TOKEN |
| App crashes on startup | Check logs for exact error, run preflight locally |

### Features Not Working
| Feature | Check |
|---------|-------|
| Telegram bot silent | BOT_TOKEN correct, logs show "Telegram polling active" |
| Twilio calls fail | NGROK_URL reachable, Twilio webhooks configured |
| Voice not working | ELEVENLABS_API_KEY valid, quota available |
| Live Listen down | FASTAPI_PORT set, live_listen/server.py error-free |

---

## 📊 Monitoring After Deployment

### Daily Checks
- [ ] Service status is "Running"
- [ ] No recent crash/restart cycles
- [ ] Logs show normal operation (no repeated errors)

### Weekly Checks
- [ ] Test each major feature (Telegram, Twilio, Voice)
- [ ] Check CPU/Memory usage is reasonable
- [ ] Verify scheduled tasks run on time
- [ ] Check error rate in logs

### Monthly Checks
- [ ] Review API quotas (ElevenLabs, Twilio, etc.)
- [ ] Check for any deprecation warnings
- [ ] Verify all features still working
- [ ] Update dependencies if needed

---

## 🔄 Auto-Deploy Workflow

After initial setup, every time you push to GitHub:

```bash
git add .
git commit -m "Your message"
git push origin main
```

Railway will:
1. Detect push
2. Build new image
3. Run preflight checks
4. Start bot
5. Replace old deployment
6. Service continues running

**Zero downtime!** 🎉

---

## 🎓 Next Steps

1. **Follow RAILWAY_QUICK_START.md** for 60-second setup
2. **Read RAILWAY.md** for detailed feature configuration
3. **Use DEPLOYMENT.md** for self-hosted setup (if needed)
4. **Monitor logs regularly** in Railway dashboard

---

## ✨ Success Indicators

✅ You're done when:
- Telegram bot responds to `/start` message
- Twilio calls are made successfully
- Voice synthesis works
- Scheduled calls execute
- LiveListen monitors calls
- No crashes in logs
- All features working as tested locally

---

## 🆘 Emergency Actions

### If service won't start
1. Check build log for errors
2. Verify all required variables are set
3. Run `python railway_preflight.py` locally
4. Check Railway logs for exact error
5. Fix locally, commit, push (will auto-redeploy)

### If service keeps crashing
1. Check error in Railway logs
2. Note exact exception
3. Fix in local code
4. Test locally: `python bot.py`
5. Commit and push (auto-redeploy)

### If features not working
1. Verify feature is enabled locally
2. Check all related env variables are set
3. Look for error messages in logs
4. Fix locally and test
5. Commit and push

---

**🚀 You're ready for production! Good luck!**
