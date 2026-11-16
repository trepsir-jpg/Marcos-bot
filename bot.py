# -*- coding: utf-8 -*-
"""Marcos — Telegram-бот компании HoliX (Python-версия для хостинга ботов).

Запуск:  python bot.py
Зависимости: requests (requirements.txt). Работает через long polling: вебхук не нужен.
Ключи берутся из переменных окружения (KEY_GEM, KEY_OR, ...). Если переменной нет, используются значения по умолчанию из этого файла.
Репозиторий должен быть ПРИВАТНЫМ: в файле лежат ключи сервисов.
"""
import base64
import calendar
import hashlib
import hmac
import json
import os
import re
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

# ---------------------------------------------------------------- настройки

def E(k, d=''):
    return (os.environ.get(k) or d).strip()

TOKEN = E('TG_TOKEN', '9073337223:AAEDzO9iWItfoIzvvrPHeg15XqCUznDlUOs')
SECRET = hashlib.sha256(('mx' + TOKEN).encode()).hexdigest()[:48]   # тот же секрет, что у версии на Netlify
KEYS = {
    'gem': E('KEY_GEM', 'AQ.Ab8RN6LLOXDaQJ82fPHAi74I2HbMmYH7OK5L5Sw887TYyebPKA'),
    'or': E('KEY_OR', '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'),
    'cfid': E('KEY_CFID', '3040f28377511f3cd6b28d1a4b8873c2'),
    'cf': E('KEY_CF', 'cfat_RlQuQw8obUGWQQbc8oA6aYeiwqgg0PhnkldwxeZF1cb7b429'),
    'sn': E('KEY_SN', '1132768a-68b2-4c66-a537-3ea0b87af412'),
    'kimi': E('KEY_KIMI', 'sk-PTdkLBGpbEc28nb8NbqQZq6vyKBN1OFD3awPeNQURHrVIVu1'),
    'dg': E('KEY_DG', '7e8eea3326918f7b5c1284ff7683beae8d84437c'),
    'di': E('KEY_DI', 'sk-di-zcSgm6SpOKQHgdMb6FTYSoj7Zf1mTlzH'),
    'co': E('KEY_CO', 'cohere_vdlyyg9WUFZyjIDWhNCFLYpjO2eRQ3cbHG8QjbgU1aP87N'),
    'ya': E('KEY_YA', 'AQVNyKMAixoI5MBjCA8_oqAl-n_Ml-aPkuu2Zw7I'),
    'yaf': E('KEY_YAF', 'b1gr1palro39ba8jnkfe'),
}
TZ = 3  # Москва, UTC+3
DATA_FILE = E('DATA_FILE', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data.json'))
API = 'https://api.telegram.org/bot' + TOKEN + '/'
UA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36'


def log(*a):
    print(datetime.now().strftime('%H:%M:%S'), *a, flush=True)

# ---------------------------------------------------------------- хранилище (JSON-файл)

class DB:
    """Простое хранилище в JSON-файле. Все операции под замком, запись атомарная."""

    def __init__(self, path):
        self.path, self.lock, self.d = path, threading.RLock(), {}
        try:
            with open(path, encoding='utf8') as f:
                self.d = json.load(f)
        except Exception:
            self.d = {}

    def get(self, k, default=None):
        with self.lock:
            return json.loads(json.dumps(self.d[k])) if k in self.d else default

    def set(self, k, v):
        with self.lock:
            self.d[k] = v
            try:
                tmp = self.path + '.tmp'
                with open(tmp, 'w', encoding='utf8') as f:
                    json.dump(self.d, f, ensure_ascii=False)
                os.replace(tmp, self.path)
            except Exception as e:
                log('db save failed', e)

db = DB(DATA_FILE)

# ---------------------------------------------------------------- Telegram

def tg(method, **body):
    r = requests.post(API + method, json=body, timeout=60 if method == 'getUpdates' else 25)
    try:
        return r.json()
    except Exception:
        return {}


def clean(t):
    t = re.sub(r'\*\*([^*]+)\*\*', r'\1', str(t or ''))
    t = re.sub(r'^#{1,3}\s+', '', t, flags=re.M)
    return re.sub(r'\n{3,}', '\n\n', t).strip()


def say(chat, text):
    text = clean(text) or '…'
    for i in range(0, len(text), 3900):
        tg('sendMessage', chat_id=chat, text=text[i:i + 3900], disable_web_page_preview=True)


def typing(chat, action='typing'):
    try:
        tg('sendChatAction', chat_id=chat, action=action)
    except Exception:
        pass


def download(file_id):
    f = tg('getFile', file_id=file_id)
    if not f.get('ok'):
        raise RuntimeError('getFile')
    r = requests.get('https://api.telegram.org/file/bot' + TOKEN + '/' + f['result']['file_path'], timeout=40)
    r.raise_for_status()
    return r.content


def send_voice(chat, data):
    r = requests.post(API + 'sendVoice', data={'chat_id': str(chat)}, files={'voice': ('marcos.ogg', data, 'audio/ogg')}, timeout=40)
    return r.json()

# ---------------------------------------------------------------- ИИ

def persona():
    now = (datetime.now(timezone.utc) + timedelta(hours=TZ)).strftime('%Y-%m-%d %H:%M')
    return ('Тебя создала компания HoliX. Ты Marcos, личный ИИ-помощник компании HoliX в Telegram. '
            'Если спрашивают, кто тебя создал или на какой ты модели, отвечай только: тебя создала компания HoliX; другие компании и названия моделей не упоминай. '
            'Отвечай по-русски (или на языке собеседника), дружелюбно, по делу и коротко: в Telegram длинные простыни неудобны. '
            'Не выдумывай факты; если не знаешь, так и скажи. Источники и ссылки не указывай, если пользователь сам не просит. '
            'Для списков используй простые дефисы, без markdown-заголовков. Сейчас: ' + now + ' по Москве.')


class HttpErr(Exception):
    def __init__(self, status):
        super().__init__('http %s' % status)
        self.status = status


def oai(url, key, model, msgs, timeout=25):
    r = requests.post(url, headers={'authorization': 'Bearer ' + key}, timeout=timeout,
                      json={'model': model, 'messages': msgs, 'stream': False, 'max_tokens': 1800})
    if not r.ok:
        raise HttpErr(r.status_code)
    t = ((r.json().get('choices') or [{}])[0].get('message') or {}).get('content')
    if not t:
        raise RuntimeError('empty')
    return re.sub(r'<think>[\s\S]*?</think>', '', str(t)).strip()


def gemini(msgs, model, extra=None):
    sys_txt = '\n'.join(m['content'] for m in msgs if m['role'] == 'system')
    contents = [{'role': 'model' if m['role'] == 'assistant' else 'user', 'parts': [{'text': m['content']}]} for m in msgs if m['role'] != 'system']
    if extra:
        contents[-1]['parts'].extend(extra)
    r = requests.post('https://generativelanguage.googleapis.com/v1beta/models/' + model + ':generateContent',
                      headers={'x-goog-api-key': KEYS['gem']}, timeout=40,
                      json={'systemInstruction': {'parts': [{'text': sys_txt}]}, 'contents': contents})
    if not r.ok:
        raise HttpErr(r.status_code)
    parts = (((r.json().get('candidates') or [{}])[0].get('content') or {}).get('parts')) or []
    t = ''.join(p.get('text', '') for p in parts if not p.get('thought')).strip()
    if not t:
        raise RuntimeError('empty')
    return t


def ai(msgs, media=None):
    errs = []
    if media:
        for m in ('gemini-2.5-flash', 'gemini-2.5-flash-lite'):
            try:
                return gemini(msgs, m, media)
            except Exception as e:
                errs.append('gem %s' % getattr(e, 'status', e))
        raise RuntimeError('Не смог посмотреть вложение (' + ', '.join(errs) + ')')
    tries = [
        lambda: oai('https://api.sambanova.ai/v1/chat/completions', KEYS['sn'], 'Meta-Llama-3.3-70B-Instruct', msgs),
        lambda: oai('https://api.moonshot.ai/v1/chat/completions', KEYS['kimi'], 'kimi-k2-turbo-preview', msgs, 35),
        lambda: gemini(msgs, 'gemini-2.5-flash'),
        lambda: oai('https://api.deepinfra.com/v1/openai/chat/completions', KEYS['di'], 'meta-llama/Llama-3.3-70B-Instruct-Turbo', msgs),
        lambda: oai('https://api.cohere.ai/compatibility/v1/chat/completions', KEYS['co'], 'command-a-03-2025', msgs),
        lambda: oai('https://api.cloudflare.com/client/v4/accounts/' + KEYS['cfid'] + '/ai/v1/chat/completions', KEYS['cf'], '@cf/meta/llama-3.3-70b-instruct-fp8-fast', msgs),
        lambda: oai('https://openrouter.ai/api/v1/chat/completions', KEYS['or'], 'meta-llama/llama-3.3-70b-instruct:free', msgs),
        lambda: oai('https://text.pollinations.ai/openai', 'x', 'openai', msgs),
    ]
    for f in tries:
        try:
            return f()
        except Exception as e:
            errs.append(str(getattr(e, 'status', e)))
    raise RuntimeError('Все сервисы ИИ не ответили (' + ', '.join(errs) + ')')

# ---------------------------------------------------------------- интернет

def _strip(s):
    s = re.sub(r'<[^>]+>', ' ', str(s or ''))
    s = s.replace('&quot;', '"').replace('&amp;', '&').replace('&#x27;', "'").replace('&#39;', "'")
    return re.sub(r'\s+', ' ', s).strip()


def web_search(q):
    out = []
    try:
        h = requests.get('https://html.duckduckgo.com/html/', params={'q': q, 'kl': 'ru-ru'}, headers={'user-agent': UA}, timeout=10).text
        rx = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)</a>[\s\S]*?<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)</a>')
        for m in rx.finditer(h):
            if len(out) >= 6:
                break
            u = m.group(1).replace('&amp;', '&')
            x = re.search(r'uddg=([^&]+)', u)
            if x:
                from urllib.parse import unquote
                u = unquote(x.group(1))
            if u.startswith('//'):
                u = 'https:' + u
            if re.match(r'^https?:', u):
                out.append({'t': _strip(m.group(2)), 'u': u, 's': _strip(m.group(3))})
    except Exception:
        pass
    if len(out) < 3:
        for lg in ('ru', 'en'):
            try:
                j = requests.get('https://%s.wikipedia.org/w/api.php' % lg, params={'action': 'query', 'list': 'search', 'srsearch': q, 'format': 'json', 'srlimit': 4}, timeout=8).json()
                for x in (j.get('query') or {}).get('search', []):
                    if len(out) < 6:
                        out.append({'t': x['title'] + ' — Википедия', 'u': 'https://%s.wikipedia.org/?curid=%s' % (lg, x['pageid']), 's': _strip(x.get('snippet'))})
                if len(out) >= 3:
                    break
            except Exception:
                pass
    return out


WEB_RE = re.compile(r'новост|сегодня|сейчас|актуальн|последн|свежи|курс |погод|цена|сколько стоит|кто выиграл|счёт|результат матч|расписани|latest|news|today|price|weather|score', re.I)


def weather(city):
    g = (requests.get('https://geocoding-api.open-meteo.com/v1/search', params={'count': 1, 'language': 'ru', 'name': city or 'Москва'}, timeout=8).json().get('results') or [None])[0]
    if not g:
        raise RuntimeError('Не нашёл город «%s»' % city)
    w = requests.get('https://api.open-meteo.com/v1/forecast', timeout=8, params={
        'latitude': g['latitude'], 'longitude': g['longitude'], 'timezone': 'auto', 'forecast_days': 1,
        'current': 'temperature_2m,apparent_temperature,weather_code,wind_speed_10m',
        'daily': 'temperature_2m_max,temperature_2m_min,precipitation_probability_max'}).json()
    c = w['current']['weather_code']
    ic = '☀️' if c == 0 else '⛅' if c < 4 else '🌫' if c < 50 else '🌧' if c < 70 else '❄️' if c < 80 else '🌦' if c < 90 else '⛈'
    d = w['daily']
    return '%s %s: %d° (ощущается %d°), ветер %d км/ч\nДнём до %d°, ночью %d°, осадки %s%%' % (
        ic, g['name'], round(w['current']['temperature_2m']), round(w['current']['apparent_temperature']), round(w['current']['wind_speed_10m']),
        round(d['temperature_2m_max'][0]), round(d['temperature_2m_min'][0]), d['precipitation_probability_max'][0] or 0)


def rates():
    r = requests.get('https://www.cbr-xml-daily.ru/daily_json.js', timeout=8).json()['Valute']
    return '💵 доллар %.2f ₽\n💶 евро %.2f ₽\n💴 юань %.2f ₽' % (r['USD']['Value'], r['EUR']['Value'], r['CNY']['Value'] / r['CNY']['Nominal'])

# ---------------------------------------------------------------- голос

def stt(buf, mime='audio/ogg'):
    r = requests.post('https://api.deepgram.com/v1/listen?model=nova-2&detect_language=true&smart_format=true&punctuate=true',
                      headers={'authorization': 'Token ' + KEYS['dg'], 'content-type': mime or 'audio/ogg'}, data=buf, timeout=30)
    if not r.ok:
        raise RuntimeError('распознавание %s' % r.status_code)
    try:
        return r.json()['results']['channels'][0]['alternatives'][0]['transcript'] or ''
    except Exception:
        return ''


def tts(text):
    t = re.sub(r'https?://\S+', '', clean(text))[:1400]
    r = requests.post('https://tts.api.cloud.yandex.net/tts/v3/utteranceSynthesis', timeout=30,
                      headers={'authorization': 'Api-Key ' + KEYS['ya'], 'x-folder-id': KEYS['yaf']},
                      json={'text': t, 'hints': [{'voice': 'denis'}, {'role': 'casual'}], 'outputAudioSpec': {'containerAudio': {'containerAudioType': 'OGG_OPUS'}}, 'loudnessNormalization': 'LUFS'})
    if not r.ok:
        raise RuntimeError('голос %s %s' % (r.status_code, r.text[:80]))
    parts = []
    for ln in r.text.splitlines():
        if not ln.strip():
            continue
        try:
            d = json.loads(ln)['result']['audioChunk']['data']
            if d:
                parts.append(base64.b64decode(d))
        except Exception:
            pass
    if not parts:
        raise RuntimeError('голос: пусто')
    return b''.join(parts)

# ---------------------------------------------------------------- время для напоминаний (Москва)

def _wall_now(now_ms=None):
    ms = now_ms if now_ms is not None else time.time() * 1000
    return datetime.fromtimestamp(ms / 1000 + TZ * 3600, timezone.utc).replace(tzinfo=None)


def _to_ms(d):
    return (calendar.timegm(d.timetuple()) - TZ * 3600) * 1000


def parse_when(t, now_ms=None):
    """Разбирает «через 20 минут», «завтра в 9:00», «в 18:30». Возвращает (метка времени в мс или 0, текст напоминания)."""
    now, d, txt = _wall_now(now_ms), None, t
    m = re.search(r'через\s+(\d+|полчаса|час|минуту)\s*(секунд\w*|сек|минут\w*|мин|час\w*|дн\w*|день|недел\w*)?', t, re.I)
    if m:
        g1, g2 = m.group(1), m.group(2)
        n = int(g1) if g1.isdigit() else 30 if re.search('полчаса', g1, re.I) else 1
        u = (g2 or ('мин' if re.search('полчаса|минуту', g1, re.I) else 'час')).lower()
        if re.search('полчаса', g1, re.I):
            u = 'мин'
        sec = 1 if 'сек' in u else 60 if 'мин' in u else 3600 if 'час' in u else 604800 if 'нед' in u else 86400
        d = now + timedelta(seconds=n * sec)
        txt = t.replace(m.group(0), '', 1)
    else:
        day = None
        if re.search('послезавтра', t, re.I):
            day, txt = 2, re.sub('послезавтра', '', t, count=1, flags=re.I)
        elif re.search('завтра', t, re.I):
            day, txt = 1, re.sub('завтра', '', t, count=1, flags=re.I)
        elif re.search('сегодня', t, re.I):
            day, txt = 0, re.sub('сегодня', '', t, count=1, flags=re.I)
        m = re.search(r'(?:(?<![а-яё])в\s+)?(\d{1,2})[:.](\d{2})', txt, re.I) or re.search(r'(?<![а-яё])в\s+(\d{1,2})\s*(час\w*|утра|вечера|дня|ночи)?', txt, re.I)
        if m:
            h = int(m.group(1))
            g2 = m.group(2) or ''
            mi = int(g2) if re.fullmatch(r'\d{2}', g2) else 0
            w = g2
            if re.search('вечера|дня', w, re.I) and h < 12:
                h += 12
            if re.search('ночи', w, re.I) and h == 12:
                h = 0
            if h > 23 or mi > 59:
                return 0, t
            d = now.replace(hour=h, minute=mi, second=0, microsecond=0)
            if day:
                d += timedelta(days=day)
            elif d <= now:
                d += timedelta(days=1)
            txt = txt.replace(m.group(0), '', 1)
        elif day is not None:
            d = now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=day)
            if d <= now:
                d += timedelta(days=1)
    text = re.sub(r'^\s*/?(remind|напомни(ть)?|напоминание)\s*(мне)?\s*[:,-]?\s*', '', txt, flags=re.I)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'^[,\s]*(что|чтобы|про|о|об)?\s*', '', text, flags=re.I).strip()
    return (_to_ms(d) if d else 0), text


def fmt_ts(ts):
    d = datetime.fromtimestamp(ts / 1000 + TZ * 3600, timezone.utc)
    return d.strftime('%d.%m %H:%M')

# ---------------------------------------------------------------- доступ и привязка

def link_code(chat):
    return hmac.new(SECRET.encode(), ('link' + str(chat)).encode(), hashlib.sha256).hexdigest()[:16]


def allowed(uid):
    env = [x for x in re.split(r'[\s,]+', E('TG_ALLOWED')) if x]
    if env:
        return str(uid) in env
    own = db.get('owner')
    if own:
        return str(own) == str(uid)
    db.set('owner', uid)   # первый, кто написал боту, становится владельцем
    return True

# ---------------------------------------------------------------- логика бота

HELP = """Я Marcos — ИИ-помощник компании HoliX.

Просто пиши или говори мне голосом — отвечу. Умею:
• /link — подключить push-уведомления из приложения Marcos
• искать в интернете: «что нового про …», /search запрос
• напоминания: «напомни через 20 минут выключить плиту», «напомни завтра в 9:00 позвонить маме»
• /tasks — мои напоминания, /del 2 — удалить второе
• /weather город — погода, /rate — курс валют
• фото: пришли картинку (можно с вопросом) — расскажу, что на ней
• файлы .txt, .md, .csv, .json — прочитаю и отвечу
• /voice on — всегда отвечать голосом, /voice off — только текстом
• /morning on — утренняя сводка в 9:00 по Москве, /morning off — выключить
• /auto on|off — отвечать за тебя в личных чатах (Telegram Business, нужен Premium)
• /persona текст — как именно отвечать за тебя
• /new — забыть этот разговор"""

db_lock = threading.RLock()   # для составных операций «прочитал → изменил → записал»


def reply(chat, text, want_voice=False):
    say(chat, text)
    if want_voice:
        try:
            typing(chat, 'record_voice')
            send_voice(chat, tts(text))
        except Exception as e:
            log('tts', e)


def think(chat, user_text, web=False, media=None):
    typing(chat)
    h = db.get('h%s' % chat, [])
    sys_parts = [persona()]
    if web or (not media and WEB_RE.search(user_text)):
        r = web_search(re.sub(r'^/search\s*', '', user_text, flags=re.I)[:200])
        if r:
            sys_parts.append('Результаты поиска в интернете. Опирайся на них для актуальных фактов. Источники, ссылки и номера в ответе не указывай. Если ответа в них нет, скажи об этом.\n'
                             + '\n'.join('[%d] %s — %s (%s)' % (i + 1, x['t'], x['s'], x['u']) for i, x in enumerate(r)))
    msgs = [{'role': 'system', 'content': '\n\n'.join(sys_parts)}] + h[-12:] + [{'role': 'user', 'content': user_text}]
    a = ai(msgs, media)
    h += [{'role': 'user', 'content': user_text[:1500]}, {'role': 'assistant', 'content': a[:2500]}]
    db.set('h%s' % chat, h[-20:])
    return a


def add_reminder(chat, text):
    ts, body = parse_when(text)
    if not body:
        return 'Что напомнить? Например: «напомни через 20 минут выключить плиту».'
    if not ts:
        return 'Не понял, когда напомнить. Напиши, например: «через 30 минут», «завтра в 9:00», «в 18:30».'
    with db_lock:
        rem = db.get('rem', [])
        rem.append({'id': os.urandom(3).hex(), 'chat': chat, 'ts': ts, 'text': body})
        db.set('rem', rem)
    return '⏰ Готово. Напомню «%s» — %s (Москва).' % (body, fmt_ts(ts))


def on(arg):
    return bool(re.match(r'^(on|вкл|да|1)', arg, re.I))


def handle_business(m):
    """Сообщение в личном чате владельца (Telegram Business): отвечаем его голосом, если автоответ включён."""
    conn_id = m.get('business_connection_id')
    if not conn_id:
        return
    conn = db.get('bizc_' + conn_id)
    if not conn or not conn.get('on'):
        return
    frm = m.get('from') or {}
    if str(frm.get('id')) == str(conn.get('user')):
        return                                   # пишет сам владелец
    text = (m.get('text') or m.get('caption') or '').strip()
    if not text:
        return                                   # фото, стикеры и голос пока пропускаем
    chat = m['chat']['id']
    key = 'bh%s_%s' % (conn_id, chat)
    h = db.get(key, [])
    sys_p = ((conn.get('persona') or 'Отвечай коротко, вежливо и по-человечески, как обычный человек в переписке.')
             + '\nТы отвечаешь в личной переписке вместо владельца аккаунта. Не говори, что ты ИИ, если не спросят прямо. '
               'Не обещай того, чего не можешь сделать, не называй деньги и сроки; если нужно решение владельца, скажи, что он ответит позже.')
    a = ai([{'role': 'system', 'content': sys_p}] + h[-10:] + [{'role': 'user', 'content': text}])
    tg('sendMessage', business_connection_id=conn_id, chat_id=chat, text=clean(a)[:3900])
    h += [{'role': 'user', 'content': text[:800]}, {'role': 'assistant', 'content': a[:1200]}]
    db.set(key, h[-16:])
    if conn.get('notify'):
        say(conn['notify'], '💬 Автоответ → %s:\n«%s»\n→ «%s»' % (frm.get('first_name') or frm.get('username') or 'собеседник', text[:200], clean(a)[:300]))


def set_auto(chat, uid, on=None, persona_text=None):
    ids = db.get('bizids', [])
    if not ids:
        return 'Сначала подключи бота: Telegram → Настройки → Telegram для бизнеса → Чат-боты → выбери этого бота (нужен Telegram Premium).'
    for cid in ids:
        c = db.get('bizc_' + cid)
        if c and str(c.get('user')) == str(uid):
            if on is not None:
                c['on'] = on
            if persona_text:
                c['persona'] = persona_text
            c['notify'] = chat
            db.set('bizc_' + cid, c)
            if on is None:
                return 'Стиль ответов сохранён.'
            return ('🤖 Автоответы включены. Я отвечаю в твоих личных чатах и присылаю сюда копии.' if on
                    else 'Автоответы выключены.')
    return 'Не нашёл твоё подключение. Добавь бота заново в «Telegram для бизнеса → Чат-боты».'


def handle(u):
    b = u.get('business_connection')
    if b:
        old = db.get('bizc_' + b['id'], {})
        db.set('bizc_' + b['id'], dict(old, user=b['user']['id'], on=False if b.get('is_enabled') is False else bool(old.get('on'))))
        ids = db.get('bizids', [])
        if b['id'] not in ids:
            ids.append(b['id'])
            db.set('bizids', ids)
        if b.get('user_chat_id'):
            say(b['user_chat_id'], '✅ Бот подключён к твоему аккаунту. Чтобы я отвечал за тебя, отправь /auto on, а стиль задай командой /persona …')
        return
    if u.get('business_message'):
        return handle_business(u['business_message'])
    m = u.get('message') or u.get('edited_message')
    if not m or not m.get('from') or m['from'].get('is_bot'):
        return
    chat, uid = m['chat']['id'], m['from']['id']
    if not allowed(uid):
        return say(chat, 'Это личный бот. Доступ закрыт.')
    text = (m.get('text') or m.get('caption') or '').strip()
    settings = db.get('set%s' % chat, {})
    cmd = re.match(r'^/(\w+)(?:@\w+)?\s*([\s\S]*)$', text)

    if cmd:
        c, arg = cmd.group(1).lower(), cmd.group(2).strip()
        if c in ('start', 'help'):
            return say(chat, HELP)
        if c == 'auto':
            flag = True if re.match(r'(on|вкл|да|1)', arg, re.I) else False if re.match(r'(off|выкл|нет|0)', arg, re.I) else None
            return say(chat, set_auto(chat, uid, flag))
        if c == 'persona':
            if not arg:
                return say(chat, 'Напиши: /persona как отвечать, например: «Я дизайнер Антон. Отвечай дружелюбно и коротко».')
            return say(chat, set_auto(chat, uid, None, arg[:800]))
        if c == 'new':
            db.set('h%s' % chat, [])
            return say(chat, 'Начали с чистого листа 🧼')
        if c == 'search':
            if not arg:
                return say(chat, 'Напиши: /search что искать')
            return reply(chat, think(chat, arg, web=True), settings.get('voice'))
        if c == 'weather':
            try:
                return say(chat, weather(arg or settings.get('city') or 'Москва'))
            except Exception as e:
                return say(chat, str(e))
        if c == 'rate':
            try:
                return say(chat, rates())
            except Exception:
                return say(chat, 'Курсы сейчас недоступны')
        if c == 'link':
            return say(chat, '🔔 Уведомления из Marcos\n\nЧат-ID: %s\nКод: %s\n\nОткрой Marcos → Настройки → Возможности → «Уведомления в Telegram» и введи эти два значения.' % (chat, link_code(chat)))
        if c == 'remind':
            return say(chat, add_reminder(chat, arg))
        if c == 'tasks':
            r = sorted([x for x in db.get('rem', []) if x['chat'] == chat], key=lambda x: x['ts'])
            return say(chat, ('Мои напоминания:\n' + '\n'.join('%d. %s — %s' % (i + 1, fmt_ts(x['ts']), x['text']) for i, x in enumerate(r)) + '\n\nУдалить: /del 1') if r else 'Напоминаний нет.')
        if c == 'del':
            with db_lock:
                allr = db.get('rem', [])
                mine = sorted([x for x in allr if x['chat'] == chat], key=lambda x: x['ts'])
                try:
                    x = mine[int(arg) - 1]
                    if int(arg) < 1:
                        raise IndexError
                except Exception:
                    return say(chat, 'Нет такого номера. Смотри /tasks')
                db.set('rem', [y for y in allr if y['id'] != x['id']])
            return say(chat, 'Удалил: ' + x['text'])
        if c == 'voice':
            settings['voice'] = on(arg)
            db.set('set%s' % chat, settings)
            return say(chat, '🔊 Буду отвечать голосом' if settings['voice'] else '🔇 Отвечаю только текстом')
        if c == 'city':
            settings['city'] = arg or 'Москва'
            db.set('set%s' % chat, settings)
            return say(chat, 'Город: ' + settings['city'])
        if c == 'morning':
            with db_lock:
                subs = [x for x in db.get('subs', []) if x != chat]
                if on(arg):
                    subs.append(chat)
                db.set('subs', subs)
            return say(chat, '☀️ Утренняя сводка включена: каждый день в 9:00 по Москве.' if on(arg) else 'Утренняя сводка выключена.')
        if c == 'ping':
            return say(chat, 'pong ✅')
        return say(chat, 'Не знаю такой команды. Список: /help')

    f = m.get('voice') or m.get('audio') or m.get('video_note')
    if f:
        typing(chat)
        try:
            tx = stt(download(f['file_id']), f.get('mime_type') or 'audio/ogg')
        except Exception as e:
            return say(chat, 'Не смог расшифровать голос: %s' % e)
        if not tx.strip():
            return say(chat, 'Не расслышал, повтори, пожалуйста.')
        say(chat, '🎙 ' + tx)
        if re.match(r'^\s*напомни', tx, re.I):
            return reply(chat, add_reminder(chat, tx), True)
        return reply(chat, think(chat, tx), True)

    if m.get('photo'):
        typing(chat, 'upload_photo')
        try:
            img = download(m['photo'][-1]['file_id'])
            a = think(chat, text or 'Опиши, что на этом фото, и расскажи самое полезное.',
                      media=[{'inlineData': {'mimeType': 'image/jpeg', 'data': base64.b64encode(img).decode()}}])
            return reply(chat, a, settings.get('voice'))
        except Exception as e:
            return say(chat, 'Не получилось разобрать фото: %s' % e)

    doc = m.get('document')
    if doc:
        if not re.search(r'^text/|json|csv|xml', doc.get('mime_type') or '') and not re.search(r'\.(txt|md|csv|json|log|html|js|py)$', doc.get('file_name') or '', re.I):
            return say(chat, 'Пока читаю только текстовые файлы: .txt, .md, .csv, .json. PDF и Word лучше открывать в приложении Marcos.')
        if (doc.get('file_size') or 0) > 400000:
            return say(chat, 'Файл слишком большой (больше 400 КБ).')
        try:
            body = download(doc['file_id']).decode('utf8', 'replace')[:24000]
            return reply(chat, think(chat, (text or 'Кратко расскажи, что в этом файле.') + '\n\n[Файл %s]\n%s' % (doc.get('file_name') or '', body)), settings.get('voice'))
        except Exception as e:
            return say(chat, 'Не смог прочитать файл: %s' % e)

    if not text:
        return
    if re.match(r'^\s*(напомни|поставь напоминание)', text, re.I):
        return say(chat, add_reminder(chat, text))
    return reply(chat, think(chat, text), settings.get('voice'))


def safe_handle(u):
    try:
        handle(u)
    except Exception as e:
        log('ошибка обработки:', traceback.format_exc())
        chat = ((u.get('message') or {}).get('chat') or {}).get('id')
        if chat:
            try:
                say(chat, 'Что-то пошло не так: %s\nПопробуй ещё раз.' % str(e)[:200])
            except Exception:
                pass

# ---------------------------------------------------------------- фоновые задачи

def reminder_loop():
    """Раз в 15 секунд отправляет сработавшие напоминания."""
    while True:
        try:
            with db_lock:
                rem = db.get('rem', [])
                now = time.time() * 1000
                due = [r for r in rem if r['ts'] <= now]
                if due:
                    db.set('rem', [r for r in rem if r['ts'] > now])
            for r in due if rem else []:
                try:
                    say(r['chat'], '⏰ Напоминаю: ' + r['text'])
                except Exception as e:
                    log('напоминание не ушло', e)
        except Exception as e:
            log('reminder_loop', e)
        time.sleep(15)


def morning_loop():
    """Каждый день в 9:00 по Москве присылает сводку подписчикам."""
    last = None
    while True:
        try:
            now = _wall_now()
            key = now.strftime('%Y-%m-%d')
            if now.hour == 9 and last != key:
                last = key
                for chat in db.get('subs', []):
                    st = db.get('set%s' % chat, {})
                    t = '☀️ Доброе утро!\n'
                    try:
                        t += '\n' + weather(st.get('city') or 'Москва')
                    except Exception:
                        pass
                    try:
                        t += '\n\n' + rates()
                    except Exception:
                        pass
                    mine = sorted([r for r in db.get('rem', []) if r['chat'] == chat and r['ts'] < time.time() * 1000 + 864e5], key=lambda r: r['ts'])
                    if mine:
                        t += '\n\nСегодня:\n' + '\n'.join('• %s — %s' % (fmt_ts(r['ts']), r['text']) for r in mine)
                    try:
                        say(chat, t)
                    except Exception:
                        pass
        except Exception as e:
            log('morning_loop', e)
        time.sleep(30)


class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b'Marcos bot: ok')

    def log_message(self, *a):
        pass


def start_health():
    port = E('PORT')
    if not port.isdigit():
        return
    srv = HTTPServer(('0.0.0.0', int(port)), Health)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    log('health on port', port)

# ---------------------------------------------------------------- запуск

def main():
    log('Marcos bot запускается…')
    me = tg('getMe')
    if not me.get('ok'):
        log('Не удалось войти в Telegram. Проверь TG_TOKEN. Ответ:', me)
        sys.exit(1)
    log('бот @%s' % me['result'].get('username'))
    tg('deleteWebhook', drop_pending_updates=False)   # long polling не работает, пока включён вебхук
    tg('setMyCommands', commands=[
        {'command': 'help', 'description': 'Что я умею'}, {'command': 'link', 'description': 'Подключить уведомления из приложения'},
        {'command': 'tasks', 'description': 'Мои напоминания'}, {'command': 'weather', 'description': 'Погода'},
        {'command': 'rate', 'description': 'Курс валют'}, {'command': 'search', 'description': 'Поиск в интернете'},
        {'command': 'voice', 'description': 'Ответы голосом: on / off'}, {'command': 'morning', 'description': 'Утренняя сводка: on / off'},
        {'command': 'auto', 'description': 'Автоответы за тебя: on / off'}, {'command': 'persona', 'description': 'Как отвечать за тебя'},
        {'command': 'new', 'description': 'Забыть разговор'}])
    start_health()
    threading.Thread(target=reminder_loop, daemon=True).start()
    threading.Thread(target=morning_loop, daemon=True).start()
    pool, offset = ThreadPoolExecutor(max_workers=8), db.get('offset', 0)
    while True:
        try:
            r = tg('getUpdates', offset=offset, timeout=50, allowed_updates=['message', 'edited_message', 'business_connection', 'business_message'])
            if not r.get('ok'):
                log('getUpdates:', r)
                time.sleep(5 if r.get('error_code') != 409 else 15)
                continue
            for u in r.get('result', []):
                offset = u['update_id'] + 1
                pool.submit(safe_handle, u)
            if r.get('result'):
                db.set('offset', offset)
        except requests.RequestException as e:
            log('сеть:', e)
            time.sleep(5)
        except KeyboardInterrupt:
            break
        except Exception:
            log(traceback.format_exc())
            time.sleep(5)


if __name__ == '__main__':
    main()
