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

    if (
        _schedule_cache["cal"] is not None
        and _schedule_cache["loaded_at"] is not None
        and now - _schedule_cache["loaded_at"] < CACHE_TTL
    ):
        return _schedule_cache["cal"]

    cal = load_schedule()

    if cal is not None:
        _schedule_cache["cal"] = cal
        _schedule_cache["loaded_at"] = now

    return cal


def _extract_event(event):
    start = event.get("dtstart")

    if start is None:
        return None

    start = start.dt

    summary = str(event.get("summary", "—"))
    location = str(event.get("location", "—"))

    # Получаем преподавателя из DESCRIPTION
    description = str(event.get("description", ""))

    teacher = "Преподаватель не указан"

    if "Преподаватель:" in description:
        teacher = description.split("Преподаватель:", 1)[1].strip()

        # Если после имени преподавателя есть лишние данные,
        # убираем их
        teacher = teacher.split("\n", 1)[0].strip()

    # Получаем время окончания
    end = event.get("dtend")

    if isinstance(start, datetime):
        start_time = start.strftime("%H:%M")

        if end is not None and isinstance(end.dt, datetime):
            end_time = end.dt.strftime("%H:%M")
            time_str = f"{start_time}–{end_time}"
        else:
            time_str = start_time

        return (
            start.date(),
            time_str,
            summary,
            location,
            teacher
        )

    else:
        return (
            start,
            "весь день",
            summary,
            location,
            teacher
        )


def format_lesson(time_str, summary, location, teacher):
    """Красиво форматирует одну пару."""

    return (
        f"🕐 <b>{time_str}</b>\n"
        f"📚 <b>{summary}</b>\n"
        f"📍 {location}\n"
        f"👨‍🏫 {teacher}"
    )


def today_list(calendar):
    if calendar is None:
        return "❌ Расписание недоступно"

    today_date = date.today()
    lessons = []

    for event in calendar.walk("VEVENT"):
        parsed = _extract_event(event)

        if not parsed:
            continue

        start_date, time_str, summary, location, teacher = parsed

        if start_date == today_date:
            lessons.append(
                (
                    time_str,
                    summary,
                    location,
                    teacher
                )
            )

    if not lessons:
        return "🎉 Сегодня пар нет"

    lessons.sort(key=lambda x: x[0])

    lines = [
        f"📅 <b>Расписание на сегодня</b>",
        ""
    ]

    for time_str, summary, location, teacher in lessons:
        lines.append(
            format_lesson(
                time_str,
                summary,
                location,
                teacher
            )
        )
        lines.append("")

    return "\n".join(lines).strip()


def tomorrow_list(calendar):
    if calendar is None:
        return "❌ Расписание недоступно"

    tomorrow_date = date.today() + timedelta(days=1)
    lessons = []

    for event in calendar.walk("VEVENT"):
        parsed = _extract_event(event)

        if not parsed:
            continue

        start_date, time_str, summary, location, teacher = parsed

        if start_date == tomorrow_date:
            lessons.append(
                (
                    time_str,
                    summary,
                    location,
                    teacher
                )
            )

    if not lessons:
        return "🎉 Завтра пар нет"

    lessons.sort(key=lambda x: x[0])

    lines = [
        f"📅 <b>Расписание на завтра</b>",
        ""
    ]

    for time_str, summary, location, teacher in lessons:
        lines.append(
            format_lesson(
                time_str,
                summary,
                location,
                teacher
            )
        )
        lines.append("")

    return "\n".join(lines).strip()


def week_list(calendar):
    if calendar is None:
        return "❌ Расписание недоступно"

    today = date.today()

    monday = today - timedelta(days=today.weekday())

    week_dates = [
        monday + timedelta(days=i)
        for i in range(7)
    ]

    events_by_date = {
        d: []
        for d in week_dates
    }

    for event in calendar.walk("VEVENT"):
        parsed = _extract_event(event)

        if not parsed:
            continue

        start_date, time_str, summary, location, teacher = parsed

        if start_date in events_by_date:
            events_by_date[start_date].append(
                (
                    time_str,
                    summary,
                    location,
                    teacher
                )
            )

    weekdays = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница",
        "Суббота",
        "Воскресенье"
    ]

    lines = [
        "📅 <b>Расписание на текущую неделю</b>",
        ""
    ]

    for d in week_dates:
        lines.append(
            f"━━━━━━━━━━━━━━━━━━\n"
            f"<b>{weekdays[d.weekday()]} · {d.strftime('%d.%m')}</b>"
        )

        lessons = events_by_date[d]

        if not lessons:
            lines.append("😴 Пар нет")
            lines.append("")
            continue

        lessons.sort(key=lambda x: x[0])

        for time_str, summary, location, teacher in lessons:
            lines.append(
                format_lesson(
                    time_str,
                    summary,
                    location,
                    teacher
                )
            )
            lines.append("")

    return "\n".join(lines).strip()

def get_weather(city="Севастополь"):
    if not OWM_KEY:
        return "❌ <b>Погода</b>\n\nКлюч OWM_KEY не задан"

    try:
        r = requests.get(
            "https://api.openweathermap.org/data/2.5/weather",
            params={
                "q": city,
                "appid": OWM_KEY,
                "units": "metric",
                "lang": "ru"
            },
            timeout=10,
        )
    except requests.RequestException as e:
        return f"❌ <b>Погода</b>\n\nОшибка сети: {e}"

    if r.status_code == 401:
        return "❌ <b>Погода</b>\n\nНеверный API-ключ"

    if r.status_code == 404:
        return f"❌ <b>Погода</b>\n\nГород «{city}» не найден"

    if r.status_code != 200:
        return f"❌ <b>Погода</b>\n\nОшибка сервера: {r.status_code}"

    try:
        data = r.json()

        temp = data["main"]["temp"]
        feels = data["main"]["feels_like"]
        pressure = data["main"]["pressure"]
        humidity = data["main"]["humidity"]

        desc = data["weather"][0]["description"]
        wind = data["wind"]["speed"]

    except (KeyError, IndexError, ValueError) as e:
        return f"❌ <b>Погода</b>\n\nНеожиданный ответ: {e}"

    weather_icon = "🌤️"

    if "ясно" in desc:
        weather_icon = "☀️"
    elif "облачно" in desc or "пасмурно" in desc:
        weather_icon = "☁️"
    elif "дожд" in desc:
        weather_icon = "🌧️"
    elif "гроза" in desc:
        weather_icon = "⛈️"
    elif "снег" in desc:
        weather_icon = "🌨️"
    elif "туман" in desc or "дым" in desc:
        weather_icon = "🌫️"

    return (
        f"🌤️ <b>Погода · {city}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"{weather_icon} <b>{desc.capitalize()}</b>\n\n"
        f"🌡️ <b>{temp:.0f}°C</b>\n"
        f"   Ощущается как {feels:.0f}°C\n\n"
        f"💨 Ветер: {wind:.1f} м/с\n"
        f"💧 Влажность: {humidity}%\n"
        f"🔵 Давление: {pressure} гПа"
    )




@bot.message_handler(commands=["start", "help"])
def cmd_start(message):
    text = (
        "👋 <b>Привет!</b>\n\n"
        "Я умею показывать расписание группы "
        "<b>ЦТ/б-24-1-о</b> и погоду.\n\n"
        "📚 <b>Расписание:</b>\n"
        "/today — пары на сегодня\n"
        "/tomorrow — пары на завтра\n"
        "/week — расписание на текущую неделю\n\n"
        "🌤 <b>Погода:</b>\n"
        "/weather — погода в Севастополе"
    )

    bot.send_message(
        message.chat.id,
        text,
        parse_mode="HTML"
    )


@bot.message_handler(commands=["today"])
def cmd_today(message):
    cal = get_schedule()

    bot.send_message(
        message.chat.id,
        today_list(cal),
        parse_mode="HTML"
    )


@bot.message_handler(commands=["tomorrow"])
def cmd_tomorrow(message):
    cal = get_schedule()

    bot.send_message(
        message.chat.id,
        tomorrow_list(cal),
        parse_mode="HTML"
    )

@bot.message_handler(commands=["week"])
def cmd_week(message):
    cal = get_schedule()

    text = week_list(cal)

    if len(text) <= 4000:
        bot.send_message(
            message.chat.id,
            text,
            parse_mode="HTML"
        )
    else:
        chunks = text.split("━━━━━━━━━━━━━━━━━━")

        for chunk in chunks:
            chunk = chunk.strip()

            if chunk:
                bot.send_message(
                    message.chat.id,
                    chunk,
                    parse_mode="HTML"
                )


@bot.message_handler(commands=["weather"])
def cmd_weather(message):
    bot.send_message(
        message.chat.id,
        get_weather(),
        parse_mode="HTML"
    )


@bot.message_handler(func=lambda m: True)
def cmd_fallback(message):
    bot.send_message(
        message.chat.id,
        "Не понимаю команду.\n\n"
        "Попробуй:\n"
        "/today\n"
        "/tomorrow\n"
        "/week\n"
        "/weather"
    )

if __name__ == "__main__":
    print("Бот запущен...")
    bot.infinity_polling()

