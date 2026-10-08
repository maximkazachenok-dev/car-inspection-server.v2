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
