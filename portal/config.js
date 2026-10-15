// =====================================================================
//  НАСТРОЙКИ САЙТА «КАРТОЧКИ ТС» — заполните перед запуском
//  Значения берутся в Supabase: Project Settings → API Keys / Data API
// =====================================================================
window.PORTAL_CONFIG = {
  // Адрес проекта Supabase, например 'https://abcdefghijkl.supabase.co'
  SUPABASE_URL: 'https://tymxijjxewxgsujbhmvv.supabase.co',
  // Публичный ключ (Publishable key, начинается с sb_publishable_).
  // Секретный ключ сюда НЕ вставлять!
  SUPABASE_KEY: 'sb_publishable_zK8cjkHzFK77O2WurFcdKQ_JnRe9McL',
  // Адрес сервера на Railway (тот же, что в config.js приложения, но без /submit).
  // Нужен для ИИ-помощника и запуска анализа фото на сайте.
  SERVER_URL: 'https://web-production-9eace.up.railway.app'
};
