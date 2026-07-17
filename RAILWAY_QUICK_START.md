# 🚀 RAILWAY DEPLOYMENT - QUICK START

## ⚡ 60-Second Setup

1. **Clone repo to Railway:**
   - Go to [railway.app](https://railway.app)
   - Click "New Project" → "Deploy from GitHub"
   - Select this repository
   - Click "Deploy"

2. **Set Environment Variables** (Critical! ⚠️):
   - Go to project Settings → Variables
   - Copy ALL variables from `.env.example`
   - Fill in YOUR values:
     - `BOT_TOKEN` - from @BotFather
     - `TWILIO_ACCOUNT_SID` - from Twilio console
     - `TWILIO_AUTH_TOKEN` - from Twilio console
     - `TWILIO_PHONE_NUMBER` - your Twilio number
     - `NGROK_URL` - your webhook URL (ngrok or Railway domain)

3. **Verify Deployment:**
   - Watch the build log (should end with "✅ Build successful")
   - Check runtime log (should show "🚀 HOTTBOIIHITZZ PREMIUM OTP BOT v4.1 STARTED")
   - Visit `https://your-domain.up.railway.app/health` → should see `{"status":"ok"}`

4. **Test the Bot:**
   - Send `/start` on Telegram
   - Check the logs for confirmation
   - Done! 🎉

---

## 🔧 What Gets Deployed

- ✅ **Telegram Bot** - Polling mode (reliable on Railway)
- ✅ **Twilio Integration** - Phone calls, SMS, OTP capture
- ✅ **ElevenLabs Voice** - Realistic speech synthesis
- ✅ **Live Listen** - Real-time call monitoring (WebSocket)
- ✅ **Scheduled Calls** - Background scheduler
- ✅ **Rate Limiting** - Security & abuse prevention
- ✅ **Web Webhooks** - Flask + FastAPI servers
- ✅ **Auto-Restart** - On failure
- ✅ **Auto-Deploy** - On git push

---

## ⚠️ Common Issues

### "Bot not responding to Telegram messages"
- [ ] Check `BOT_TOKEN` is set correctly
- [ ] Check build log shows "Starting application in full mode"
- [ ] Look for "Telegram polling active" in logs

### "Twilio calls not working"
- [ ] Verify `NGROK_URL` is set (webhook URL)
- [ ] Configure Twilio webhooks: `{NGROK_URL}/voice` and `{NGROK_URL}/twilio/status`
- [ ] Check Twilio console for webhook delivery failures

### "Build failing - ModuleNotFoundError"
- [ ] All dependencies are in `requirements.txt`
- [ ] Check build log for exact error
- [ ] May need to add missing package to requirements.txt

### "App crashing on startup"
- [ ] Check variables are set (not `YOUR_XXX` placeholders)
- [ ] Run `python railway_preflight.py` locally to debug
- [ ] Check exact error in runtime logs

---

## 📖 Full Documentation

See **[RAILWAY.md](RAILWAY.md)** for comprehensive setup, troubleshooting, and feature configuration.

---

## 🆘 Need Help?

1. Check logs in Railway dashboard
2. Read [RAILWAY.md](RAILWAY.md) troubleshooting section
3. Run `python railway_preflight.py` locally to diagnose
4. Verify all `.env.example` variables are set in Railway

---

## ✨ You're Ready!

Your OTP bot is now production-ready. Push to GitHub and Railway handles the rest! 🚀
