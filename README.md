# Осмотр ТС — версия 2 (сайт «Карточки ТС»)

| Часть | Файлы | Где работает |
|---|---|---|
| Приложение водителя | `index.html`, `config.js`, `manifest.json`, `sw.js`, `icon-*.png` | GitHub Pages: `…/car-inspection-v2/` |
| Сайт «Карточки ТС» | `portal/` | GitHub Pages: `…/car-inspection-v2/portal/` |
| Сервер | `server.py`, `sessions.py`, `supa.py`, `notify.py`, `requirements.txt`, `Procfile` | Railway |
| База данных | `supabase/001_init.sql` | Supabase (тестовый проект) |
| Проверки | `tests/` | локально: `python -m pytest tests` |

## Запуск тестового контура

1. **Supabase.** Зарегистрировать новый аккаунт, создать проект → SQL Editor → выполнить `supabase/001_init.sql`.
   - Authentication → Users → Add user: 1–2 пользователя сайта (email + пароль, Auto Confirm).
   - Authentication → Sign In / Providers → **Allow new users to sign up — выключить**.
   - Project Settings → API Keys: Publishable key (для сайта) и Secret key (для сервера).
2. **GitHub.** Новый аккаунт → репозиторий `car-inspection-v2` (Public) → загрузить содержимое папки `v2`
   (кроме `.env`) → Settings → Pages → main / root.
3. **Railway.** Новый аккаунт (вход через новый GitHub) → сервис из репозитория `car-inspection-v2` → Variables: значения из `.env.example`
   → Settings → Networking → Generate Domain.
4. **Настройки на сайте и в приложении:**
   - `config.js`: `SERVER_URL = https://<адрес Railway>/submit`, `APP_TOKEN` = `API_TOKEN` из Railway;
   - `portal/config.js`: `SUPABASE_URL` и **Publishable** key (секретный ключ сюда не вставлять).
5. Открыть сайт → войти → добавить ТС и водителей (вручную или из Excel) → оформить приёмку в приложении.

Проект v2 разворачивается на **отдельных новых аккаунтах** GitHub, Railway и Supabase.
Адреса строятся от нового логина GitHub: приложение `https://НОВЫЙ-ЛОГИН.github.io/car-inspection-v2/`,
сайт — тот же адрес + `portal/`. В Railway обязательно задать `ALLOWED_ORIGINS=https://НОВЫЙ-ЛОГИН.github.io`
и `PORTAL_URL`, иначе приложение получит «Нет соединения с сервером».

## Переход водителей на v2

Новый аккаунт GitHub = новый адрес приложения. При переходе водители один раз открывают новый адрес
и заново добавляют приложение на главный экран; старый контур после этого отключается.

## ИИ-помощник на сайте (этап от 15.10.2026)

Раздел «Помощник» на сайте отвечает на вопросы по осмотрам обычным языком, а в карточке ТС появилась кнопка
«Запустить анализ ИИ». ИИ вызывается только через сервер: ключ хранится в Railway, сервер принимает вопросы
только от вошедших на сайт.

Подключение (один раз):

1. **Supabase** → SQL Editor → выполнить `supabase/002_assistant.sql`.
2. **Railway** (проект новой версии) → Variables → `ANTHROPIC_KEY` = ключ из console.anthropic.com (на счёте должны быть деньги).
3. **GitHub** → загрузить изменённые файлы: `server.py`, `assistant.py`, `notify.py`, `supa.py`, `requirements.txt`,
   `Procfile`, `supabase/002_assistant.sql`, `tests/test_assistant.py`, `portal/app.js`, `portal/api.js`, `portal/ui.css`,
   `portal/config.js` (в нём добавлен `SERVER_URL` — адрес сервера Railway без `/submit`).
   Файл `config.js` в корне **не загружать**: на GitHub лежит рабочая версия с ключом приложения.
4. Проверка: `https://<адрес Railway>/api/health` → строка `"помощник": "готов"`.

### Модель помощника (с 19.10.2026)

Модель ИИ-помощника задаётся в Railway переменной `ASSISTANT_MODEL`. Без неё работает `claude-opus-5-5`.
Можно: `claude-opus-5-5`, `claude-sonnet-5-5`, `claude-haiku-5-5`, `claude-opus-5`, `claude-fable-5-1`.
Если название с ошибкой, помощник продолжает работать на `claude-opus-5-5`, а `/api/health` пишет предупреждение
в строке «модель помощника». Анализ фото (Sonnet 4.6) и команда «сравни» в Telegram (Haiku 4.5) этой переменной не меняются.

## Замечания и отметка «Замечания устранены» (с 19.10.2026)

1. **Supabase** → SQL Editor → выполнить `supabase/003_remarks.sql`.
2. Загрузить на GitHub изменённые файлы (`portal/app.js`, `portal/api.js`, `portal/ui.css`, `assistant.py`, тесты, этот README).

До выполнения скрипта сайт работает как раньше, а в столбце «Замечания» стоит «—».
Какой текст водителя не считается замечанием («всё хорошо», «нет» и т.п.) — список в `003_remarks.sql`
(функция `is_driver_remark`) и такой же в `assistant.py` (`NO_REMARK_PHRASES`); менять оба места.
