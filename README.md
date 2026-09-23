# AI Sana Challenge Hub

MVP для HackAlem AI / AI Sana Hackathon. Этап 1: черновики бизнес-задач, SQLite и детерминированный рейтинг полноты. React + Vite и существующая проверка связи с FastAPI сохранены. AI API пока не подключён; backend/agent.py и backend/tools.py — заготовки для следующего этапа.

## Подготовка (Windows PowerShell)

Нужны Python 3.11 и Node.js 24 LTS (проверено на 24.18.0), Git.

```powershell
git clone https://github.com/BAITC-Hacks/hack-20246846-kai-education.git
cd hack-20246846-kai-education
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm ci
cd ..
```

## Запуск

В первом терминале из корня проекта:

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
```

Во втором терминале из корня проекта:

```powershell
cd frontend
npm run dev -- --host localhost --port 5173 --strictPort
```

Открыть http://localhost:5173 и нажать «Проверить Backend». Ожидаемый результат: «Статус: ok».

Backend: http://127.0.0.1:8000/health возвращает {"status":"ok"}. Документация API: http://127.0.0.1:8000/docs.

Используйте именно localhost:5173 для frontend: этот адрес разрешён настройкой CORS. Если порт занят, проверьте уже запущенные терминалы; повторный запуск не нужен. Для остановки нажмите Ctrl+C в соответствующем терминале.

## Проверки frontend

Из папки frontend:

```powershell
npm run lint
npm run build
```

## Локальные файлы

.env, .venv/, node_modules/, dist/ и кеши Python исключены из Git. Текущая заготовка не требует .env или API-ключей. Не добавляйте секреты в исходный код.


## Этап 1: API задач

Работает без OpenAI и API-ключа. Сервис сохраняет только введённые сведения, ничего не извлекает и не придумывает из черновика. Поле draft хранит исходное описание; структурированные поля заполняются явно через API.

| Метод | Адрес | Назначение |
|---|---|---|
| POST | /challenges | Создать черновик, HTTP 201 |
| GET | /challenges/{id} | Получить карточку и актуальный рейтинг |
| PATCH | /challenges/{id} | Частично изменить карточку и пересчитать рейтинг |
| POST | /challenges/{id}/readiness | Пересчитать рейтинг сохранённой карточки |
| GET | /health | Прежний health check |

Ответ карточки содержит id, draft, все структурированные поля, published=false, readiness_score, readiness_level, breakdown, missing_information и recommendations. Ответ пересчёта содержит только рейтинг, уровень, разбивку, недостающие поля и рекомендации.

При создании обязателен непустой draft (до 20 000 символов). Остальные текстовые поля необязательны и ограничены 10 000 символами каждое. Пробелы по краям удаляются. PATCH меняет только переданные поля; пустая строка очищает структурированное поле. Пустой PATCH, null, неверные типы, неизвестные поля и попытки задать id/published/рейтинг возвращают 422. Некорректный UUID — 422, отсутствующая задача — 404, ошибка SQLite — 503. Валидация сообщает проблемное поле в detail.

Публикации на этом этапе нет: даже 100 баллов не меняют published. Рейтинг всегда вычисляется из сохранённых полей и не хранится отдельным устаревающим значением.

### Правила рейтинга

| Критерий | Баллы |
|---|---|
| context + need | 10 + 10 |
| data_and_materials | 20 |
| expected_result | 15 |
| success_criteria | 15 |
| constraints | 10 |
| users | 10 |
| contact + interaction_format | 5 + 5 |

Каждое непустое поле получает указанный вес целиком. Пустое поле получает 0. title, industry и исходный draft на баллы не влияют. Явное описание отсутствия данных или ограничений считается предоставленной информацией. Это оценка заполненности, а не качества, истинности или реализуемости задачи: произвольный непустой текст тоже получает баллы.

Уровни: 0–39 Draft; 40–69 Working; 70–89 Ready; 90–100 Priority. breakdown содержит score и max_score для семи критериев. missing_information перечисляет пустые оцениваемые поля, recommendations объясняет, что добавить и сколько баллов это даст.

### Ручная проверка

Запустите backend командой выше и откройте http://127.0.0.1:8000/docs. Либо выполните в PowerShell:

```powershell
$base = 'http://127.0.0.1:8000'
Invoke-RestMethod "$base/health"
$body = @{draft='We want to improve customer support'} | ConvertTo-Json
$challenge = Invoke-RestMethod "$base/challenges" -Method Post -ContentType 'application/json' -Body $body
$challenge # score=0, level=Draft, published=False
$edit = @{context='Online shop'; need='Reduce repetitive questions'; data_and_materials='FAQ and anonymized support tickets'} | ConvertTo-Json
Invoke-RestMethod "$base/challenges/$($challenge.id)" -Method Patch -ContentType 'application/json' -Body $edit
# score=40, level=Working
Invoke-RestMethod "$base/challenges/$($challenge.id)/readiness" -Method Post
Invoke-RestMethod "$base/challenges/$($challenge.id)"
```

После перезапуска backend GET с тем же id должен вернуть сохранённую карточку. Для проверки снижения баллов отправьте PATCH с {"context":""}: результат — 30, Draft.

### SQLite и тесты

SQLite создаётся при запуске в backend/data/challenges.sqlite3 (путь не зависит от текущей папки терминала). Одна таблица challenges хранит id, JSON полей и published=0. База и служебные файлы SQLite исключены из Git. Частичные обновления выполняются в транзакции; подключения закрываются после запроса. ORM и миграции пока не нужны.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

Тесты используют отдельные временные базы, не трогают рабочие данные и не обращаются к OpenAI. httpx нужен только для FastAPI TestClient; unittest и sqlite3 входят в Python.

### Границы этапа

Авторизации и проверки владения задачами пока нет; запуск рассчитан на локальную разработку. Нет публикации, каталога, предложений команд и AI-анализа. Следующий этап: анализ черновика, минимум три уточняющих вопроса, ответы и подтверждаемая пользователем структурированная карточка; отдельный AI-адаптер с fallback без ключа. Scoring остаётся независимым от AI.
