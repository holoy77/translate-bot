
# Discord Translator Bot

A production-ready Discord bot that automatically detects and translates
text and audio messages using Google Gemini AI.
All responses and help commands are available in both English and Japanese.

Version : 2.1.0
Authors : testerxma — https://github.com/testerxma
         

---

## Table of Contents

1.  Features
2.  Requirements
3.  Installation
4.  Configuration
5.  Running the Bot
6.  Commands
7.  How to Use
8.  Language Support
9.  Audio Support
10. Architecture
11. Troubleshooting
12. Project Structure
13. Credits

---

## 1. Features

### Text Translation
Translate any text message by replying to it and mentioning the bot.
The source language is detected automatically — no manual input required.

### Audio Transcription and Translation
Attach an audio file to a message, reply to it, and mention the bot.
The bot downloads the file, transcribes it using Gemini, and returns
both the original transcript and the translation.

### Bilingual Interface — English and Japanese
Every bot response, error message, help board, and status display
is shown in both English and Japanese side by side.
A dedicated Japanese help dashboard is available via !helpja.

### 18 Supported Languages
Arabic, Japanese, English, French, Spanish, German, Korean, Chinese,
Russian, Turkish, Italian, Portuguese, Hindi, Indonesian, Polish,
Dutch, Thai, Vietnamese.

### Multi-Model Fallback
Six Gemini models are tried in priority order with exponential backoff.
If one model hits a quota or is unavailable, the next is tried automatically.
This maximises free-tier uptime across the daily quota window.

### Automatic Language Detection
Gemini detects the source language from the content itself.
No language flags or prefixes are needed from the user.

### Per-User Language Preferences
Each user can set their own personal target language using !lang.
Preferences are stored in user_prefs.json and survive bot restarts.
Other users in the same server are not affected by another user's setting.

### Per-User Cooldowns with Auto-Pruning
A configurable cooldown is applied per user after each successful translation.
The cooldown dictionary prunes expired entries automatically to prevent
memory growth over time.

### Per-Guild Concurrency Limiting
Each server is limited to a configurable number of simultaneous translations.
This prevents any single server from consuming all available API capacity.

### Sliding Window RPM Control
All Gemini API calls pass through a sliding-window rate limiter backed
by a semaphore. This prevents exceeding the requests-per-minute limit
even under concurrent load.

### Persistent Storage with Atomic Writes
User preferences are written using a temporary file that is moved into
place atomically. This prevents data corruption if the bot is interrupted
during a write.

### Safe Embed Output
All translated content has @everyone and @here tokens escaped before
being placed into Discord embeds. This prevents accidental mass mentions.

### Task GC Safety
Background translation tasks are tracked in a set to prevent them from
being garbage collected mid-execution by the Python runtime.

---

## 2. Requirements

| Package       | Minimum Version |
|---------------|-----------------|
| Python        | 3.10            |
| discord.py    | 2.0             |
| google-genai  | 1.0             |
| pydantic      | 2.0             |
| python-dotenv | any             |

---

## 3. Installation

### Step 1 — Clone the Repository

```bash
git clone https://github.com/testerxma/discord-translator-bot.git
cd discord-translator-bot
```

### Step 2 — Create a Virtual Environment

Windows:
```bash
python -m venv venv
venv\Scripts\activate
```

macOS and Linux:
```bash
python3 -m venv venv
source venv/bin/activate
```

### Step 3 — Install Dependencies

```bash
pip install -r requirements.txt
```

### Step 4 — Create the .env File

Create a file named .env in the project root directory:

```
DISCORD_TOKEN=your_discord_bot_token_here
GEMINI_API_KEY=your_gemini_api_key_here
```

Rules:
- No spaces around the equals sign
- No quotes around the values
- Never share or commit this file to version control

Add it to .gitignore immediately:

```bash
echo ".env" >> .gitignore
```

---

## 4. Configuration

### 4.1 Discord Bot Token

1. Go to https://discord.com/developers/applications
2. Click "New Application" and give it a name
3. Go to "Bot" in the left sidebar
4. Click "Reset Token" and copy the token
5. Paste it into your .env file as DISCORD_TOKEN=

### 4.2 Enable Required Intents

Go to:

```
Discord Developer Portal
-> Your Application
-> Bot
-> Privileged Gateway Intents
```

Enable the following:

```
[x] Presence Intent
[x] Server Members Intent
[x] Message Content Intent    <- Required
```

### 4.3 Invite the Bot to Your Server

Go to:

```
Discord Developer Portal
-> Your Application
-> OAuth2
-> URL Generator
```

Select Scopes:

```
[x] bot
[x] applications.commands
```

Select Bot Permissions:

```
General:
    [x] View Channels

Text:
    [x] Send Messages
    [x] Send Messages in Threads
    [x] Embed Links
    [x] Attach Files
    [x] Read Message History
    [x] Use Slash Commands

Voice:
    [x] Connect
    [x] Speak
    [x] Use Voice Activity
```

Permissions Integer:
```
2184301632
```

Direct invite link (replace CLIENT_ID with your application ID):
```
https://discord.com/oauth2/authorize?client_id=CLIENT_ID&permissions=2184301632&integration_type=0&scope=bot+applications.commands
```

### 4.4 Gemini API Key

1. Go to https://aistudio.google.com/app/apikey
2. Click "Create API Key"
3. Copy the key
4. Paste it into your .env file as GEMINI_API_KEY=

Note:
    The free tier includes generous daily limits.
    The bot automatically rotates through 6 Gemini models
    to maximise free-tier uptime before quota is exhausted.
    Quotas reset daily at approximately midnight Pacific Time.

### 4.5 Optional — Tuning Constants

These values are defined at the top of bot.py and can be adjusted:

| Constant                | Default | Description                                      |
|-------------------------|---------|--------------------------------------------------|
| USER_COOLDOWN_SECONDS   | 15      | Seconds a user must wait between requests        |
| MAX_AUDIO_SIZE_MB       | 20      | Maximum audio file size in megabytes             |
| MAX_CONCURRENT_PER_GUILD| 3       | Maximum simultaneous translations per server     |
| GEMINI_RPM_LIMIT        | 10      | Maximum Gemini requests per 60-second window     |
| MAX_FALLBACK_WAIT_SECS  | 8       | Maximum total seconds spent on fallback retries  |
| GEMINI_SEMAPHORE_SIZE   | 1       | Number of concurrent Gemini calls allowed        |

---

## 5. Running the Bot

### Standard Start

```bash
python bot.py
```

### Expected Startup Output

```
13:00:00 [INFO] Gemini API initialised — 6 models available
13:00:00 [INFO] Loaded 3 user preferences from user_prefs.json
13:00:01 [INFO] ----------------------------------------
13:00:01 [INFO]   Translator Bot v2.1.0
13:00:01 [INFO]   Made by: testerxma & uaaw
13:00:01 [INFO] ----------------------------------------
13:00:01 [INFO] Bot online  : TranslatorBot#1234 (ID: 123456789)
13:00:01 [INFO] Servers     : 1
13:00:01 [INFO] Models      : 6 available
13:00:01 [INFO] Languages   : 18 supported
13:00:01 [INFO] Cooldown    : 15s per user
13:00:01 [INFO] ----------------------------------------
```

### Running as a Background Service

Windows — no console window:
```bash
pythonw bot.py
```

Linux — using systemd:

Create /etc/systemd/system/translator-bot.service:

```ini
[Unit]
Description=Discord Translator Bot
After=network.target

[Service]
Type=simple
User=your_linux_username
WorkingDirectory=/path/to/bot
ExecStart=/path/to/venv/bin/python bot.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then run:

```bash
sudo systemctl enable translator-bot
sudo systemctl start translator-bot
sudo systemctl status translator-bot
```

---

## 6. Commands

### Translation — No Command Required

| Action                       | How                                                      |
|------------------------------|----------------------------------------------------------|
| Translate a text message     | Reply to the message and mention @BotName                |
| Translate an audio file      | Reply to the message with the audio and mention @BotName |

---

### !help

Show the full English help dashboard with all commands, limits, and usage.

```
!help
```

---

### !helpja

日本語のヘルプダッシュボードを表示します。
Show the full Japanese help dashboard.
Includes all commands, language codes, limits, and usage in Japanese.

```
!helpja
```

---

### !lang

Set your personal target translation language.
Run with no argument to view your current setting.
Response is shown in both English and Japanese.

```
!lang <code>
```

Examples:

```
!lang en      Set target to English / 英語に設定
!lang ja      Set target to Japanese / 日本語に設定
!lang ar      Set target to Arabic / アラビア語に設定
!lang fr      Set target to French / フランス語に設定
!lang         View your current setting / 現在の設定を確認
```

---

### !langs

List all 18 supported language codes.
Each entry shows the English name and the Japanese name side by side.

```
!langs
```

Output format:

```
ar  —  Arabic  /  アラビア語
de  —  German  /  ドイツ語
en  —  English  /  英語
es  —  Spanish  /  スペイン語
fr  —  French  /  フランス語
hi  —  Hindi  /  ヒンディー語
id  —  Indonesian  /  インドネシア語
it  —  Italian  /  イタリア語
ja  —  Japanese  /  日本語
ko  —  Korean  /  韓国語
nl  —  Dutch  /  オランダ語
pl  —  Polish  /  ポーランド語
pt  —  Portuguese  /  ポルトガル語
ru  —  Russian  /  ロシア語
th  —  Thai  /  タイ語
tr  —  Turkish  /  トルコ語
vi  —  Vietnamese  /  ベトナム語
zh  —  Chinese  /  中国語
```

---

### !resetlang

Clear your custom language preference.
Restores the default Arabic to Japanese auto-swap behaviour.
Response is shown in both English and Japanese.

```
!resetlang
```

---

### !status

Show the bot's current stats and your personal settings.
All fields are labelled in both English and Japanese.

```
!status
```

Shows:

```
Target Language / 翻訳先言語     Your current setting or default
Cooldown / クールダウン           Ready or seconds remaining
Active / 実行中                  Current translations out of max
Models / モデル数                 Number of Gemini fallback models
Servers / サーバー数              Total servers the bot is in
Languages / 対応言語数            Total supported language codes
Version / バージョン              Current bot version
```

---

### !owners

Display information about the bot's creators with GitHub links.
Description is shown in both English and Japanese.

```
!owners
```

---

## 7. How to Use

### Translating a Text Message

1. Find any message in the server you want to translate
2. Right-click the message and select Reply
3. In your reply, mention the bot with @BotName
4. Send the message

The bot will:
- Auto-detect the source language
- Apply your personal target language or use the default logic
- Reply with a formatted embed showing the original and translation
- Label all fields in both English and Japanese

Example:

```
User A writes  :  marhaban, kayfa haluk?
User B replies :  @TranslatorBot

Bot replies:

    User A
    ------
    原文 / Original — Arabic
    marhaban, kayfa haluk?

    翻訳 / Translation — Japanese
    こんにちは、お元気ですか？
```

### Translating an Audio File

1. Find a message that contains an audio attachment
2. Reply to that message and mention @BotName
3. The bot will:
   - Validate the file size
   - Download the audio file locally
   - Upload it to Gemini for transcription
   - Translate the transcribed text
   - Return both the transcript and the translation
   - Clean up the uploaded file from Gemini servers automatically

### Setting a Personal Target Language

1. Run !lang en
2. All translations you request will now target English
3. Other users are not affected — preferences are per-user
4. Run !resetlang to go back to the default behaviour

### Default Translation Logic

| Source Language    | Target Language |
|--------------------|-----------------|
| Arabic             | Japanese        |
| Japanese           | Arabic          |
| Any other language | English         |

Use !lang to override this for your own requests.

### Viewing Help in Japanese

Run !helpja to see the full command reference in Japanese.
All language codes are listed with their Japanese names.
All limits and usage instructions are written in Japanese.

---

## 8. Language Support

| Code | English Name | Japanese Name    |
|------|--------------|------------------|
| ar   | Arabic       | アラビア語        |
| de   | German       | ドイツ語          |
| en   | English      | 英語              |
| es   | Spanish      | スペイン語        |
| fr   | French       | フランス語        |
| hi   | Hindi        | ヒンディー語      |
| id   | Indonesian   | インドネシア語    |
| it   | Italian      | イタリア語        |
| ja   | Japanese     | 日本語            |
| ko   | Korean       | 韓国語            |
| nl   | Dutch        | オランダ語        |
| pl   | Polish       | ポーランド語      |
| pt   | Portuguese   | ポルトガル語      |
| ru   | Russian      | ロシア語          |
| th   | Thai         | タイ語            |
| tr   | Turkish      | トルコ語          |
| vi   | Vietnamese   | ベトナム語        |
| zh   | Chinese      | 中国語            |

To add more languages, edit the LANG_LABEL and LANG_LABEL_JA dictionaries
in bot.py and add the full language name to LANG_CODE_ALIASES.

---

## 9. Audio Support

### Supported Formats

| Format | Extension |
|--------|-----------|
| MP3    | .mp3      |
| WAV    | .wav      |
| OGG    | .ogg      |
| M4A    | .m4a      |
| WebM   | .webm     |
| FLAC   | .flac     |
| Opus   | .opus     |
| WMA    | .wma      |
| AAC    | .aac      |

### Limits

| Limit             | Value                                        |
|-------------------|----------------------------------------------|
| Maximum file size | 20 MB (configurable via MAX_AUDIO_SIZE_MB)   |
| Processing time   | 5 to 15 seconds depending on length and load |

### How Audio Processing Works

1. File size is validated before any download begins
2. The file is saved to a local temporary file
3. The temporary file is uploaded to Gemini File API
4. Gemini transcribes and translates the audio
5. The uploaded file is deleted from Gemini servers
6. The local temporary file is deleted
7. Results are posted as a Discord embed

---

## 10. Architecture

```
bot.py
|
|-- Environment and Constants
|       DISCORD_TOKEN, GEMINI_API_KEY loaded from .env
|       All tuneable limits and metadata defined at the top
|
|-- Language Data
|       LANG_LABEL        English language names
|       LANG_LABEL_JA     Japanese language names
|       LANG_CODE_ALIASES Full name to code mapping for Gemini output
|
|-- Gemini Layer
|       _throttled_gemini_call()       Sliding-window RPM + semaphore
|       _try_generate_with_fallback()  6-model waterfall with backoff
|       process_text()                 Text input  -> TranslationResponse
|       process_audio()                Audio input -> TranslationResponse
|
|-- User Preferences
|       user_prefs.json                Persistent JSON storage
|       _load_prefs() / _save_prefs()  Atomic writes via .tmp swap
|       get_user_lang()                Read preference
|       set_user_lang()                Write preference
|       clear_user_lang()              Delete preference
|       is_user_on_cooldown()          Check and prune cooldown dict
|
|-- Safety and Limits
|       _guild_increment/decrement()   Per-guild concurrency counter
|       _safe_embed_value()            Escapes @everyone and @here
|       _normalise_lang_code()         Normalises Gemini language output
|       download_audio()               Size check before file download
|       _background_tasks set          Prevents task GC mid-execution
|
|-- Discord Bot
        on_ready()        Sync slash commands, log startup banner
        on_message()      Detect mentions and reply references
        handle_request()  Main translation orchestrator
        Commands:
            !help         English help dashboard
            !helpja       Japanese help dashboard
            !lang         Set or view personal target language
            !langs        List all supported languages (EN + JA)
            !resetlang    Clear personal language preference
            !status       Bot stats and personal settings (EN + JA)
            !owners       Creator information and GitHub links
```

---

## 11. Troubleshooting

### Bot does not respond to mentions

Check the following:
- MESSAGE CONTENT INTENT is enabled in the Developer Portal
- The bot has Read Message History permission in the channel
- The bot role is not restricted by other server roles
- You are replying to an existing message, not sending a new one

---

### Error: PrivilegedIntentsRequired on startup

```
Go to:
    https://discord.com/developers/applications
    -> Your Application
    -> Bot
    -> Privileged Gateway Intents
    -> Enable: MESSAGE CONTENT INTENT
    -> Save Changes
    -> Restart the bot
```

---

### Error: TypeError: Files.upload() got an unexpected keyword argument 'path'

Your google-genai SDK is outdated. Run:

```bash
pip install --upgrade google-genai
```

The API changed between versions:

```python
# Old — no longer works
gemini_client.files.upload(path=audio_path)

# New — correct usage
gemini_client.files.upload(file=audio_path)
```

---

### Error: DISCORD_TOKEN is missing

Check the following:
- The .env file exists in the same folder as bot.py
- It contains the line: DISCORD_TOKEN=your_token_here
- There are no spaces around the equals sign
- There are no quotes around the token value

---

### Translation targets the wrong language

```
!lang          View your current preference
!resetlang     Clear your preference and restore default
!lang en       Set a specific target language
```

---

### All Gemini models are quota exhausted

The bot cycles through 6 Gemini models automatically.
If all are exhausted:

- Free tier quotas reset daily at approximately midnight Pacific Time
- Wait and try again the next day
- Upgrade to a paid Gemini API plan for higher limits:
  https://ai.google.dev/gemini-api/docs/pricing

---

### Bot says the server is busy

The server has reached MAX_CONCURRENT_PER_GUILD simultaneous requests.
Default limit is 3.

- Wait for current translations to finish
- Increase MAX_CONCURRENT_PER_GUILD in bot.py if needed

---

### Japanese text is not displaying correctly

Make sure your system and Discord client support Unicode and CJK characters.
The bot uses standard UTF-8 encoding for all output.
No additional configuration is required on the bot side.

---

## 12. Project Structure

```
discord-translator-bot/
|
|-- bot.py              Main bot file
|-- .env                Your secrets — never commit this file
|-- .env.example        Template showing required environment variables
|-- .gitignore          Excludes secrets and generated files from git
|-- requirements.txt    Python package dependencies
|-- user_prefs.json     Auto-created on first use of !lang
|-- README.md           This file
```

### .env.example

```
# Copy this file to .env and fill in your real values
# Never commit your actual .env file to version control

DISCORD_TOKEN=your_discord_bot_token_here
GEMINI_API_KEY=your_gemini_api_key_here
```

### .gitignore

```
# Secrets
.env

# Python
__pycache__/
*.pyc
*.pyo
venv/
.venv/

# Bot runtime data
user_prefs.json
user_prefs.json.tmp

# OS files
.DS_Store
Thumbs.db
desktop.ini

# IDE files
.vscode/
.idea/
*.swp
```

### requirements.txt

```
discord.py>=2.0.0
google-genai>=1.0.0
pydantic>=2.0.0
python-dotenv>=1.0.0
```

---

## 13. Credits

| Name      | Role                  | GitHub                        |
|-----------|-----------------------|-------------------------------|
| testerxma | Co-Creator, Developer | https://github.com/testerxma |
---

Translator Bot v2.1.0
Made by testerxma — https://github.com/testerxma
    
```
