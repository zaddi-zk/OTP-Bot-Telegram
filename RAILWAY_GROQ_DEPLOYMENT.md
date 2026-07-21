# Railway Deployment Guide - Groq + ElevenLabs + PostgreSQL

## Overview
This guide walks through deploying the OTP Bot with:
- **Groq API** for fast LLM (llama-3.1-8b-instant, <2s latency)
- **ElevenLabs** for human-like voice synthesis
- **PostgreSQL** for user persistence (Railway)
- **Telegram Bot** for user interactions
- **Twilio** for phone call handling

---

## Step 1: Create Railway Project

1. Go to https://railway.app/
2. Create new project → "Deploy from GitHub"
3. Connect your repo: `OTP-Bot-Telegram-clean`
4. Select Node/Python environment

---

## Step 2: Set Environment Variables in Railway

Go to **Project → Variables** and add these:

### **LLM (Groq)**
```
GROQ_API_KEY=<your-groq-api-key>
GROQ_MODEL=llama-3.1-8b-instant
```
**Get Groq API key:** https://console.groq.com/keys

### **Voice Synthesis (ElevenLabs)**
```
ELEVENLABS_API_KEY=sk_d2b06b0c5856ef511e9991ee62bdbd3ab8d2f25b0a86077c
DEFAULT_ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
ELEVENLABS_MODEL=eleven_turbo_v2
```
(Rachel voice ID for professional bank agent tone)

### **Database (PostgreSQL)**
Railway auto-provides this when you add PostgreSQL plugin:
```
DATABASE_URL=<auto-provided by Railway>
```

### **Telegram Bot**
```
BOT_TOKEN=<your-telegram-bot-token>
OWNER_ID=<your-telegram-user-id>
ADMIN_ID=<admin-telegram-id>
MAIN_CHANNEL_ID=@your_channel
MAIN_CHANNEL_URL=https://t.me/your_channel
BACKUP_CHANNEL_ID=@backup_channel
BACKUP_CHANNEL_URL=https://t.me/backup_channel
```

### **Twilio**
```
TWILIO_ACCOUNT_SID=<your-account-sid>
TWILIO_AUTH_TOKEN=<your-auth-token>
TWILIO_PHONE_NUMBER=+1234567890
NGROK_URL=https://your-ngrok-url.ngrok-free.dev
```

### **Optional Settings**
```
DEBUG=false
USE_AI_FLOW=true
VOUCH_CHANNEL_ID=-1004364877298
FREE_TRIAL_CALLS=5
RATE_LIMIT_CAPACITY=10
```

---

## Step 3: Connect PostgreSQL

1. In Railway project, click **"Create Database"**
2. Select **"PostgreSQL"**
3. Railway auto-adds `DATABASE_URL` to variables

---

## Step 4: Deploy

1. Railway auto-detects `requirements.txt`
2. Installs dependencies
3. Runs `bot.py` as entrypoint

Verify in **Deployments** → logs should show:
```
[INFO] ✅ Bot started successfully
[INFO] ✅ DATABASE_URL is configured
[INFO] [LLM-Groq] Ready
```

---

## Step 5: Test the Flow

### Local Test (Before Deployment)
```bash
export GROQ_API_KEY=your-key
export ELEVENLABS_API_KEY=your-key
python scripts/test_groq_normal_call.py
```

### Production Test (After Deployment)
1. Start the Telegram bot
2. Click "Start Call" → Normal Call
3. Bot initiates call to your phone via Twilio
4. Groq generates response → ElevenLabs speaks it
5. Whisper transcribes your response
6. Loop continues until OTP is verified

---

## Environment Variable Checklist

| Variable | Required | Source | Default |
|----------|----------|--------|---------|
| `GROQ_API_KEY` | ✅ | https://console.groq.com | (none) |
| `ELEVENLABS_API_KEY` | ✅ | https://elevenlabs.io | (none) |
| `BOT_TOKEN` | ✅ | @BotFather on Telegram | (none) |
| `TWILIO_ACCOUNT_SID` | ✅ | https://www.twilio.com | (none) |
| `TWILIO_AUTH_TOKEN` | ✅ | https://www.twilio.com | (none) |
| `TWILIO_PHONE_NUMBER` | ✅ | Twilio Console | (none) |
| `DATABASE_URL` | ✅ | Railway PostgreSQL | (none) |
| `NGROK_URL` | ✅ | https://ngrok.com | (none) |
| `DEFAULT_ELEVENLABS_VOICE_ID` | ⚠️ | ElevenLabs Console | "21m00Tcm4TlvDq8ikWAM" |
| `OWNER_ID` | ⚠️ | Your Telegram ID | (none) |
| `USE_AI_FLOW` | ❌ | Config | true |
| `GROQ_MODEL` | ❌ | Config | llama-3.1-8b-instant |

---

## Troubleshooting

### Groq API Errors
- `[LLM-Groq] HTTP 401`: API key invalid
- `[LLM-Groq] Timeout (10s)`: Network issue, check Railway outbound connectivity

**Solution**: Verify `GROQ_API_KEY` is correct, test locally first.

### ElevenLabs Not Speaking
- `[TTS] 404 Client Error`: Voice ID not found
- `[TTS] 401 Unauthorized`: API key invalid

**Solution**: Check `DEFAULT_ELEVENLABS_VOICE_ID` and `ELEVENLABS_API_KEY`.

### Database Connection Failed
- `DATABASE_URL not configured`: PostgreSQL plugin not added

**Solution**: Add PostgreSQL from Railway marketplace.

### Twilio Calls Not Receiving
- Webhook not registering

**Solution**: Check `NGROK_URL` is public and set in Twilio console.

---

## Key Features Preserved

✅ OTP extraction from speech  
✅ Conversation memory (last 8 turns)  
✅ Emotion-aware responses (calm, urgent, assertive)  
✅ Human-like tone (bank security agent)  
✅ Stays on-topic (won't discuss unrelated topics)  
✅ Never breaks character  
✅ PostgreSQL user persistence  
✅ Telegram bot integration  
✅ Twilio media stream integration  
✅ Whisper transcription  

---

## Performance Metrics

- **LLM Response**: <2 seconds (Groq, 10ms network latency)
- **TTS Generation**: 1-2 seconds (ElevenLabs)
- **Total Call Loop**: 3-4 seconds (user speaks → AI responds → plays audio)
- **Concurrency**: 2-4 simultaneous calls (depends on Railway plan)

---

## Cost Estimate (Monthly)

| Service | Est. Cost |
|---------|-----------|
| Railway (bot + DB) | $10-20 |
| Groq API | Free tier (10k tokens/min) or $0.50-1/mo |
| ElevenLabs | ~$5-10 (1k characters/mo included) |
| Twilio | $1-3 (depends on call volume) |
| NGROK | Free tier or $7-13 |
| **TOTAL** | **$25-50/month** |

---

## Next Steps

1. Get Groq API key: https://console.groq.com
2. Verify ElevenLabs API key (provided: `sk_d2b06...`)
3. Set variables in Railway
4. Deploy
5. Test with `/start` in Telegram bot

---

**Support**: Check Railway logs in real-time:
```bash
railway logs -f
```

---

*Last updated: 2026-07-21*
*Groq LLM migration complete. All existing features preserved.*
