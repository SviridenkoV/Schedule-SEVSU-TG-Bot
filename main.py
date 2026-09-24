import os
import requests
import telebot
from dotenv import load_dotenv
from icalendar import Calendar
from datetime import datetime, date, timedelta

load_dotenv()
OWM_KEY = os.getenv("OWM_KEY")
bot_api = os.getenv("bot_token")
bot = telebot.TeleBot(bot_api)

SCHEDULE_URL = "https://schedule.sevsu.ru/calendar/group/6BDF4DDC90540455"

_schedule_cache = {"cal": None, "loaded_at": None}
CACHE_TTL = timedelta(minutes=30)


def load_schedule():
    try:
        r = requests.get(SCHEDULE_URL, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"[расписание] не удалось скачать: {e}")
        return None

    if "BEGIN:VCALENDAR" not in r.text:
        print("[расписание] сервер вернул не ICS")
        return None

    try:
        return Calendar.from_ical(r.text)
    except Exception as e:
        print(f"[расписание] ошибка парсинга: {e}")
        return None


def get_schedule():
    """Возвращает календарь, используя кэш."""
    now = datetime.now()
    if (_schedule_cache["cal"] is not None
            and _schedule_cache["loaded_at"] is not None
            and now - _schedule_cache["loaded_at"] < CACHE_TTL):
        return _schedule_cache["cal"]

    cal = load_schedule()
    if cal is not None:
        _schedule_cache["cal"] = cal
        _schedule_cache["loaded_at"] = now
    return cal


def _extract_event(event):
    start = event.get('dtstart')
    if start is None:
        return None
    start = start.dt

    if isinstance(start, datetime):
        return start.date(), start.strftime('%H:%M'), \
               event.get('summary', '—'), event.get('location', '—')
    else:
        return start, 'весь день', \
               event.get('summary', '—'), event.get('location', '—')


def today_list(calendar):
    if calendar is None:
        return "Расписание недоступно"
    today_date = date.today()
    lines = []
    for event in calendar.walk('VEVENT'):
        parsed = _extract_event(event)
        if not parsed:
            continue
        start_date, time_str, summary, location = parsed
        if start_date == today_date:
            lines.append(f"{time_str} | {summary} | {location}")
    return "\n".join(lines) if lines else "Сегодня пар нет"


def tomorrow_list(calendar):
    if calendar is None:
        return "Расписание недоступно"
    tomorrow_date = date.today() + timedelta(days=1)
    lines = []
    for event in calendar.walk('VEVENT'):
        parsed = _extract_event(event)
        if not parsed:
            continue
        start_date, time_str, summary, location = parsed
        if start_date == tomorrow_date:
            lines.append(f"{time_str} | {summary} | {location}")
    return "\n".join(lines) if lines else "Завтра пар нет"


def week_list(calendar):
    if calendar is None:
        return "Расписание недоступно"
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    week_dates = [monday + timedelta(days=i) for i in range(7)]
    events_by_date = {d: [] for d in week_dates}

    for event in calendar.walk('VEVENT'):
        parsed = _extract_event(event)
        if not parsed:
            continue
        start_date, time_str, summary, location = parsed
        if start_date in events_by_date:
            events_by_date[start_date].append((time_str, summary, location))

    out = []
    for d in week_dates:
        out.append(f"\n=== {d.strftime('%d.%m (%a)')} ===")
        if not events_by_date[d]:
            out.append("Пар нет")
        else:
            for time_str, summary, location in sorted(events_by_date[d]):
                out.append(f"{time_str} | {summary} | {location}")
    return "\n".join(out)

def get_weather(city="Севастополь"):
    if not OWM_KEY:
        return "Погода: ключ OWM_KEY не задан"
    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={"q": city, "appid": OWM_KEY, "units": "metric", "lang": "ru"},
            timeout=10,
        )
    except requests.RequestException as e:
        return f"Погода: ошибка сети ({e})"

    if r.status_code == 401:
        return "Погода: неверный API-ключ"
    if r.status_code == 404:
        return f"Погода: город «{city}» не найден"
    if r.status_code != 200:
        return f"Погода: ошибка {r.status_code}"

    try:
        data = r.json()
        temp = data["main"]["temp"]
        feels = data["main"]["feels_like"]
        desc = data["weather"][0]["description"]
        wind = data["wind"]["speed"]
    except (KeyError, IndexError, ValueError) as e:
        return f"Погода: неожиданный ответ ({e})"

    return f"{city}: {desc}, {temp:.0f}°C (ощущается {feels:.0f}°C), ветер {wind} м/с"



@bot.message_handler(commands=['start', 'help'])
def cmd_start(message):
    text = (
        "Привет! Я умею показывать расписание группы ЦТ/б-24-1-о и погоду.\n\n"
        "Команды:\n"
        "/today — пары на сегодня\n"
        "/tomorrow — пары на завтра\n"
        "/week — расписание на текущую неделю\n"
        "/weather — погода в Севастополе"
    )
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=['today'])
def cmd_today(message):
    cal = get_schedule()
    bot.send_message(message.chat.id, today_list(cal))


@bot.message_handler(commands=['tomorrow'])
def cmd_tomorrow(message):
    cal = get_schedule()
    bot.send_message(message.chat.id, tomorrow_list(cal))


@bot.message_handler(commands=['week'])
def cmd_week(message):
    cal = get_schedule()
    text = week_list(cal)

    if len(text) <= 4000:
        bot.send_message(message.chat.id, text)
    else:

        for chunk in text.split("\n=== "):
            if chunk.strip():
                bot.send_message(message.chat.id, "=== " + chunk if not chunk.startswith("===") else chunk)


@bot.message_handler(commands=['weather'])
def cmd_weather(message):
    bot.send_message(message.chat.id, get_weather())


@bot.message_handler(func=lambda m: True)
def cmd_fallback(message):
    bot.send_message(
        message.chat.id,
        "Не понимаю команду. Попробуй /today, /tomorrow, /week или /weather."
    )



if __name__ == "__main__":
    print("Бот запущен...")
    bot.infinity_polling()