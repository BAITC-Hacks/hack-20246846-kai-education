# Adaptive Learning Agent

Техническая заготовка для хакатона: React + Vite и FastAPI. Трек и функции проекта будут определены после выдачи задания. AI API пока не подключён; backend/agent.py и backend/tools.py — пустые заготовки.

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
