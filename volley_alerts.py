import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import json
import os
import re
import logging

from telegram import Bot, Update
from telegram.ext import Updater, CommandHandler, CallbackContext

# Configurazione
URL = "https://www.volleyball.ch/fr/game-center?sport=indoor&gender=m&season=2025&i_tab=Championnat&i_region=SV&i_league=6609&i_phase=12968&i_group=27046&i_week=5"
TEAM_KEYWORD = "Caslano"    # case-insensitive
STATE_FILE = "volley_state.json"

TELE_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN"
CHAT_ID = "YOUR_CHAT_ID"

headers = {"User-Agent": "CaslanoNotifier/1.0 (+https://yourdomain.example)"}

bot = Bot(token=TELE_TOKEN)

def notify_text(text):
    bot.send_message(chat_id=CHAT_ID, text=text)

def cmd_online(update: Update, context: CallbackContext):
    update.message.reply_text("✅ Bot attivo — ora: " + datetime.utcnow().isoformat() + "Z")

def setup_bot():
    updater = Updater(TELE_TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("online", cmd_online))
    # Non blocca; se vuoi esecuzione continua dello scraping, puoi farlo in thread separato
    updater.start_polling()
    return updater

def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE, "r", encoding="utf-8"))
    return {"matches": {}}

def save_state(state):
    json.dump(state, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def fetch_page(url):
    r = requests.get(url, headers=headers, timeout=20)
    r.raise_for_status()
    return r.text

def parse_matches(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    matches = []
    for i, line in enumerate(lines):
        if re.search(r"\b" + re.escape(TEAM_KEYWORD) + r"\b", line, re.I):
            window = " ".join(lines[max(0,i-5):i+6])
            date_match = re.search(r"(\d{1,2}[./]\d{1,2}[./]\d{2,4})|(\d{4}-\d{2}-\d{2})|(\d{1,2}\s+\w+\s+\d{4})", window)
            date_str = date_match.group(0) if date_match else None
            vs_match = re.search(r"([A-Za-zÀ-ÖØ-öø-ÿ0-9 '\-\.]+)\s*(?:-|–|—|vs\.?|v\.)\s*([A-Za-zÀ-ÖØ-öø-ÿ0-9 '\-\.]+)", window, re.I)
            home, away = None, None
            if vs_match:
                a,b = vs_match.group(1).strip(), vs_match.group(2).strip()
                if re.search(r"\b" + TEAM_KEYWORD + r"\b", a, re.I):
                    home, away = a, b
                elif re.search(r"\b" + TEAM_KEYWORD + r"\b", b, re.I):
                    home, away = b, a
                else:
                    home, away = a, b
            set_scores = re.findall(r"(\d{1,2})\s*[-:]\s*(\d{1,2})", window)
            set_scores = [(int(x), int(y)) for x,y in set_scores] if set_scores else []
            matches.append({
                "context_line": line,
                "date_raw": date_str,
                "home": home,
                "away": away,
                "set_scores": set_scores,
                "scraped_at": datetime.utcnow().isoformat() + "Z"
            })
    return matches

def parse_date(date_raw):
    if not date_raw:
        return None
    for fmt in ("%d.%m.%Y","%d.%m.%y","%Y-%m-%d","%d %B %Y","%d %b %Y"):
        try:
            return datetime.strptime(date_raw, fmt)
        except Exception:
            pass
    return None

def run_scrape():
    state = load_state()
    html = fetch_page(URL)
    matches = parse_matches(html)
    now = datetime.utcnow()
    for m in matches:
        dt = parse_date(m.get("date_raw"))
        key = (m.get("home") or "") + "|" + (m.get("away") or "") + "|" + (m.get("date_raw") or "")
        if key not in state["matches"]:
            state["matches"][key] = {"seen_at": now.isoformat(), "notified": False, "reported": False, "last": m}
        # notificare 2 giorni prima
        if dt:
            days_until = (dt - now).days
            if days_until <= 2 and days_until >= 0 and not state["matches"][key].get("notified"):
                notify_text(f"In {days_until} giorni: {m.get('home')} vs {m.get('away')} il {m.get('date_raw')}")
                state["matches"][key]["notified"] = True
        # report dei risultati
        if m["set_scores"] and not state["matches"][key].get("reported"):
            sets_home = sum(1 for s in m["set_scores"] if s[0] > s[1])
            sets_away = sum(1 for s in m["set_scores"] if s[1] > s[0])
            winner = m["home"] if sets_home > sets_away else m["away"] if sets_away > sets_home else "pareggio"
            notify_text(f"Risultato: {m.get('home')} vs {m.get('away')} - Winner: {winner} | Sets H:{sets_home} A:{sets_away} | Set scores: {m['set_scores']}")
            state["matches"][key]["reported"] = True
        state["matches"][key]["last"] = m
    save_state(state)

if __name__ == "__main__":
    bot_updater = setup_bot()
    # Se vuoi puoi schedule lo scraping dentro lo stesso processo, ma se usi GitHub Actions / scheduler esterno solo:
    run_scrape()
    # Mantieni il bot attivo se è sempre in ascolto
    bot_updater.idle()
