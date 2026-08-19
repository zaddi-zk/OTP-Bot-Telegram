# 🚀 Railway Deployment Guide - OTP Bot Telegram

This guide will help you deploy your entire OTP bot to Railway with **all features working** (Telegram webhooks, Vapi calls over Asterisk + SpoofGlobal, FastAPI LiveListen, scheduled calls, and more).

---

## ✅ Pre-Deployment Checklist

Before deploying, ensure you have:

- [x] GitHub repository with code pushed
- [x] Telegram bot token from @BotFather
- [x] Vapi API key and Vapi SIP phone number ID
- [x] Asterisk CLI (AMI) available for the call trunk
- [x] ElevenLabs API key (for voice)
- [x] ngrok or alternative webhook URL (for Vapi webhooks)
- [x] Owner/Admin/Developer IDs
- [x] Wallet addresses for payments (BTC/ETH/USDT)

---

## 🔌 Step 1: Connect GitHub to Railway

1. Go to [railway.app](https://railway.app)
2. Sign in or create an account
3. Create a **new project** → **Deploy from GitHub**
4. Connect your GitHub account
5. Select the `OTP-Bot-Telegram-clean` repository
6. Choose **main** branch
7. Click **Deploy**

Railway will automatically:
- Install dependencies via `railway.toml`
- Start the bot via `python bot.py`
- Monitor and restart on failure

---

## 🎯 Step 2: Set Environment Variables in Railway

**Critical!** Your bot will NOT work without these. Go to:
**Settings → Variables** and add ALL of these:

### **TELEGRAM CONFIGURATION**
```
BOT_TOKEN=<your-telegram-bot-token>
USE_WEBHOOK=false              # Use polling for reliability on Railway
```

### **VAPI & TELEPHONY CONFIGURATION** (Required for phone calls)
```
VAPI_API_KEY=<your-vapi-api-key>
VAPI_SIP_PHONE_NUMBER_ID=<your-vapi-sip-phone-number-id>
USE_ASTERISK=true
ASTERISK_TRUNK=<asterisk-trunk-name>
ASTERISK_CLI_DIR=conf/asterisk_cli
NGROK_URL=https://your-ngrok-url.ngrok-free.dev
```

**⚠️ NGROK_URL:** If you're using ngrok to expose webhooks:
- Start ngrok: `ngrok http 5000`
- Copy the HTTPS URL: `https://abc123.ngrok-free.dev`
- Set `NGROK_URL` to this value
- Point the Vapi webhook to `{NGROK_URL}/vapi/webhook`

**Alternative:** Use Railway's built-in domain:
- Your service gets: `https://otp-bot-railway-production.up.railway.app`
- Set `NGROK_URL=https://otp-bot-railway-production.up.railway.app`
- Point the Vapi webhook URL to this domain

### **TELEGRAM CHANNELS**
```
MAIN_CHANNEL_URL=https://t.me/your_channel
BACKUP_CHANNEL_URL=https://t.me/your_backup
MAIN_CHANNEL_ID=@your_channel    # or numeric ID
BACKUP_CHANNEL_ID=@your_backup
```

### **ADMINS & USERS**
```
OWNER_ID=123456789
ADMIN_ID=987654321
DEVELOPER_IDS=123456789,987654321
```

### **VOICE & AUDIO** (ElevenLabs for realistic speech)
```
ELEVENLABS_API_KEY=<your-api-key>
DEFAULT_ELEVENLABS_VOICE_ID=<voice-id>   # e.g., EXAVITQu4vr4xnSDxMaL
ELEVENLABS_MODEL=eleven_turbo_v2
VOICE_STABILITY=0.45
VOICE_SIMILARITY_BOOST=0.75
```

### **PAYMENTS** (Your crypto wallets)
```
PAYMENT_BTC=bc1...your-btc-address
PAYMENT_ETH=0x...your-eth-address
PAYMENT_USDT=0x...your-usdt-address
PAYMENT_LTC=L...your-ltc-address
FREE_TRIAL_CALLS=5
```

### **LIVE LISTEN** (FastAPI WebSocket for call recording)
```
LIVE_LISTEN_SECRET=<generate-a-random-secret>
LIVE_LISTEN_URL=https://otp-bot-railway-production.up.railway.app
FASTAPI_PORT=5001
```

### **SERVER & DEPLOYMENT**
```
PORT=5000                  # Railway will set this automatically
FLASK_PORT=5000
DEBUG=false                # NEVER true in production
```

### **OPTIONAL: Redis** (for distributed rate limiting)
```
REDIS_URL=redis://...     # Only if you add Redis add-on
```

---

## 🚀 Step 3: Verify the Deployment

1. **Check Build Logs:**
   - Go to **Deployments** tab
   - Click the latest deployment
   - Verify "Build successful" message
   - Check "✅ Build successful" in output

2. **Check Runtime Logs:**
   - Go to **Logs** tab
   - Look for:
     ```
     Starting application in full mode
     Flask server started on 0.0.0.0:5000
     FastAPI server started on 0.0.0.0:5001
     ```

3. **Health Check:**
   - Visit: `https://your-railway-domain.up.railway.app/health`
   - Should return: `{"status":"ok"}`

4. **Test Telegram Webhook:**
   - Send a message to your bot on Telegram
   - Check logs for message processing

---

## 🔄 Step 4: Configure Vapi Webhook

After getting your Railway domain, point Vapi's webhook at your bot:

1. Go to the [Vapi Dashboard](https://dashboard.vapi.ai)
2. **Settings → Webhook**
3. **URL:** `https://your-railway-domain.up.railway.app/vapi/webhook`
4. Save

---

## 🎵 Step 5: Verify All Features

### ✅ Telegram Polling
- Send `/start` to your bot
- Should respond with menu
- Check logs: `Telegram polling active`

### ✅ Vapi Calls
- Use bot command to make a call
- Check logs for call initiation
- Vapi should receive webhook callbacks (call.inProgress, transcript, end-of-call)

### ✅ Voice Generation
- Make a call with voice option
- ElevenLabs API should be called
- Should hear synthesized voice

### ✅ Live Listen
- Monitor a live call via web interface
- FastAPI should handle WebSocket connections

### ✅ Scheduled Calls
- Create a scheduled call
- Scheduler background thread should execute
- Check logs: `Executing scheduled call`

---

## 🛡️ Troubleshooting

### Bot not responding to messages
```
Solution:
1. Verify BOT_TOKEN is correct
2. Check logs for "Starting application in full mode"
3. Ensure USE_WEBHOOK=false (polling mode is more reliable)
```

### Vapi calls not working
```
Solution:
1. Verify VAPI_API_KEY and VAPI_SIP_PHONE_NUMBER_ID are correct
2. Verify NGROK_URL is reachable (if using ngrok)
3. Check Vapi call logs in the Vapi dashboard for errors
```

### FastAPI (Live Listen) not working
```
Solution:
1. Verify FASTAPI_PORT=5001 is set
2. Check logs for "FastAPI server started"
3. Ensure live_listen/server.py is working locally
```

### App crashing on startup
```
Solution:
1. Check Build Logs for dependency installation errors
2. Verify all env vars are set (don't use YOUR_XXX placeholders)
3. Check Railway Logs for Python exceptions
```

### Can't hear voice in calls
```
Solution:
1. Verify ELEVENLABS_API_KEY is correct
2. Check ElevenLabs account has quota
3. Verify DEFAULT_ELEVENLABS_VOICE_ID is valid
```

---

## 📊 Monitoring & Logs

Railway automatically shows:
- **Build Logs** - Dependency installation, compilation errors
- **Deployment Logs** - Startup sequence
- **Runtime Logs** - Live application output

### Key Log Messages to Look For

✅ **Successful startup:**
```
Starting application in full mode.
Flask server started on 0.0.0.0:5000
FastAPI server started on 0.0.0.0:5001
Telegram polling active
Background threads started.
Main process entering keepalive loop
```

❌ **Errors to watch for:**
```
ModuleNotFoundError - missing dependency
BOT_TOKEN not configured - telegram won't start
Cannot bind Flask to port 5000 - port conflict
FastAPI uvicorn failed - check live_listen/server.py
```

---

## 🔄 Auto-Deploy on Push

Your Railway project is linked to GitHub. Every time you `git push origin main`:

1. GitHub notifies Railway
2. Railway pulls latest code
3. Runs build step (installs dependencies)
4. Runs start step (starts `bot.py`)
5. Old deployment is replaced
6. Service restarts automatically

No manual action needed!

---

## 💾 Persistent Storage

Railway provides **ephemeral storage** (lost on restart). For persistent data:

1. **Keep data in `conf/` folder** - Railway mounts it
2. **Optional: Add Railway Database** (PostgreSQL/MySQL)
3. **Optional: Add Railway Redis** (for rate limiting, caching)

---

## 🎓 Next Steps

1. **Test locally first:**
   ```bash
   python bot.py
   ```
   
2. **Commit and push to GitHub:**
   ```bash
   git add -A
   git commit -m "Update Railway deployment config"
   git push origin main
   ```

3. **Watch Railway deployment** in the dashboard

4. **Monitor logs** in real-time

5. **Test all features** via Telegram bot

---

## 📞 Support

- **Telegram Issues:** Check `bot.py` logging, verify BOT_TOKEN
- **Vapi Issues:** Check Vapi dashboard for call/webhook failures
- **Railway Issues:** Check deployment logs, restart service
- **Voice Issues:** Verify ElevenLabs API key and quota

---

## ✨ You're All Set!

Your OTP bot is now running on Railway with:
- ✅ Telegram bot (polling mode for stability)
- ✅ Vapi phone calls (via Asterisk + SpoofGlobal)
- ✅ ElevenLabs voice synthesis
- ✅ Live Listen (FastAPI WebSocket)
- ✅ Scheduled calls (background scheduler)
- ✅ Rate limiting & security
- ✅ Auto-restart on failure
- ✅ Auto-deploy on git push

Enjoy! 🎉
