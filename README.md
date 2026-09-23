# AI Sana Challenge Hub

MVP для HackAlem AI / AI Sana Hackathon. Этапы 1–2: черновики бизнес-задач, SQLite, детерминированный рейтинг и AI-предложения карточек с ручным подтверждением. React + Vite и существующая проверка связи с FastAPI сохранены. OpenAI подключается через backend/ai_provider.py; backend/agent.py и backend/tools.py остаются неиспользуемыми заготовками.

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

Авторизации и проверки владения задачами пока нет; запуск рассчитан на локальную разработку. Нет публикации, каталога и предложений студенческих команд. AI workflow этапа 2 описан ниже. Scoring остаётся независимым от AI.

## Этап 2: AI-анализ и предложенная карточка

Весь workflow доступен через Swagger; frontend не менялся. Слово card-proposals означает предложения полей карточки от AI, а не заявки студенческих команд.

### Настройки OpenAI

Проверенный установленный SDK: openai==3.19.0. Используется официальный Responses API, client.responses.parse(text_format=PydanticModel), строгий Structured Output. Документация: https://developers.openai.com/api/docs/guides/structured-outputs

Установите зависимости:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

В корневом .env задайте OPENAI_API_KEY и OPENAI_MODEL. В .env.example только пустые значения и комментарии. Не перезаписывайте существующий .env командой копирования, если в нём есть ваши настройки.

```dotenv
OPENAI_API_KEY=<ваш настоящий API ключ>
OPENAI_MODEL=<ID доступной вам модели с Responses и Structured Outputs>
```

Модель не задана по умолчанию: замените оба значения вместе с угловыми скобками. Без ключа ИЛИ модели AI endpoint вернёт fallback/not_configured. Переменные окружения процесса имеют приоритет над .env. Секрет читается только backend; префикс VITE_ использовать нельзя. Настройки не возвращаются в API и не записываются в БД. .env не изменялся при реализации.

Один запрос анализа или построения карточки делает один запрос OpenAI: timeout 30 секунд, автоматические повторы выключены, store=false. SDK-клиент закрывается после запроса. Реальные вызовы могут тарифицироваться; automated tests используют mock и не вызывают OpenAI.

### Новые endpoints

| Метод | Путь | Назначение |
|---|---|---|
| POST | /challenges/{id}/analysis | Анализ draft, известные сведения, недостающие категории, минимум 3 вопроса |
| POST | /challenges/{id}/card-proposals | Ответы на вопросы → отдельное AI-предложение карточки |
| GET | /challenges/{id}/card-proposals/{proposal_id} | Просмотр предложения и исходной карточки |
| POST | /challenges/{id}/card-proposals/{proposal_id}/confirm | Подтверждение с необязательными ручными правками |

Анализ и построение возвращают HTTP 200 со status=ok либо status=fallback. При fallback доступны code, message и manual_edit_available=true; фиктивных AI-карточек или вопросов не генерируется. Коды: not_configured, unavailable, invalid_output. При ошибке остаются доступны PATCH и readiness этапа 1. Нет анализа/предложения для этой задачи — 404, неверный запрос — 422, устаревшее или повторное подтверждение — 409.

Анализ содержит known_information, evidence, missing_information и questions с id (q1, q2, …), field, kind и text. Для неизвестной категории kind=missing; когда категорий не хватает меньше трёх, модель должна спрашивать только ещё не описанные детали (kind=detail), не повторять известные факты. Дубликаты вопросов и вопросы kind=missing о найденных полях отклоняются. missing_information вычисляется backend по извлечённым полям девяти обязательных категорий.

### Ручная проверка с настоящим ключом

1. Запустите backend и откройте http://127.0.0.1:8000/docs.
2. Создайте Challenge через POST /challenges с непустым draft и сохраните id.
3. Выполните POST /challenges/{id}/analysis (без body). При status=ok сохраните analysis_id и прочитайте вопросы.
4. Ответьте на вопросы через POST /challenges/{id}/card-proposals. Подставьте настоящий analysis_id, соответствующие question_id и ваши ответы:

```json
{
  "analysis_id": "UUID из ответа анализа",
  "answers": [
    {"question_id": "q1", "text": "Ответ бизнеса на первый вопрос"},
    {"question_id": "q2", "text": "Ответ бизнеса на второй вопрос"},
    {"question_id": "q3", "text": "Ответ бизнеса на третий вопрос"}
  ]
}
```

Можно ответить на часть вопросов, но минимум на один. Неизвестные поля остаются пустыми. Суммарный размер ответов — до 30 000 символов.

5. Получите proposal_id. Просмотрите proposed_card, current_card и evidence. GET Challenge до подтверждения должен вернуть прежние данные и рейтинг. Предложение хранится отдельно и доступно после перезапуска.
6. Для принятия отправьте POST /challenges/{id}/card-proposals/{proposal_id}/confirm:

```json
{
  "confirmed": true,
  "edits": {
    "title": "Название, подтверждённое бизнесом"
  }
}
```

edits можно опустить или передать пустой объект. В него входят только поля карточки; пустая строка очищает поле. Ручные правки — новые сведения самого пользователя, поэтому они не ограничены цитатами AI. Значения null, draft, published и readiness_score в edits запрещены.

7. Confirm заменяет ВСЕ структурированные поля на просмотренную proposed_card с вашими edits. Пустые поля предложения тоже применяются: сравните с current_card перед подтверждением, чтобы сохранить нужные прежние сведения через edits. Исходный draft сохраняется. Backend пересчитывает readiness прежним scoring engine; published остаётся false. GET Challenge показывает итог.
8. Если Challenge изменился после анализа (включая ручной PATCH), повторите анализ и построение предложения: устаревшее предложение не перезапишет новые данные. Повторный confirm возвращает 409.

### Защита от выдуманных сведений и ограничения

- Каждое непустое AI-поле — точная цитата с source_id из draft или конкретного answer:qN. Backend проверяет наличие цитаты именно в указанном источнике. Текст вопроса не является источником фактов.
- Неизвестные поля возвращаются как null в ответе модели и как пустые строки в proposed_card. Произвольный текст не разбирается регулярными выражениями.
- Некорректная схема, выдуманная цитата, отказ модели или незавершённый ответ дают явный fallback. Challenge не изменяется.
- AI не получает инструментов записи в БД, публикации или выбора команды. Scoring не передаётся модели.
- Цитирование не доказывает правильность смыслового отнесения фразы к полю. Ошибки интерпретации, неполное извлечение и неудачные вопросы возможны: просмотр и ручное подтверждение обязательны. В MVP нет свободного перефразирования и придуманного заголовка, поэтому title/industry часто остаются пустыми.
- При очень полном draft требование трёх вопросов реализуется вопросами о дополнительных неуказанных деталях. Их полезность зависит от модели.
- Используются две таблицы SQLite: исходные challenges и отдельная ai_workflows с анализами, ответами и предложениями. Добавление таблицы не меняет существующие Challenge. Подтверждение и отметка confirmed выполняются одной транзакцией. Автоматического удаления старых workflow пока нет.
- Авторизации, rate limiting и UI workflow пока нет. Реальный вызов OpenAI при реализации не выполнялся: ключ и модель не настроены. Следующий этап не реализован.

### Тесты

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -v
```

Старые 14 тестов сохранены. Новые тесты проверяют анализ, минимум три вопроса, строгие схемы, источники цитат, отсутствие сохранения до confirm, ручные правки, пересчёт, fallback, устаревшие предложения, повторное подтверждение, сохранение workflow между запусками и параметры SDK. Все AI-вызовы замоканы.
