const BASE = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

export async function request(path, { method = 'GET', body, signal } = {}) {
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 45000)
  const abort = () => controller.abort()
  signal?.addEventListener('abort', abort, { once: true })
  if (signal?.aborted) controller.abort()
  try {
    const response = await fetch(`${BASE}${path}`, {
      method, headers: body ? { 'Content-Type': 'application/json' } : undefined,
      body: body ? JSON.stringify(body) : undefined, signal: controller.signal,
    })
    let data
    try { data = await response.json() } catch { throw new Error('Сервер вернул неожиданный ответ. Повторите попытку.') }
    if (!response.ok) {
      const messages = {
        404: 'Задача или предложение не найдены. Обновите страницу.',
        409: typeof data.detail === 'string' ? data.detail : 'Данные изменились. Обновите их и повторите действие.',
        422: 'Проверьте заполнение полей. Обязательные поля не должны быть пустыми, ссылка должна начинаться с https:// или http://.',
        503: 'Сервис временно недоступен. Повторите попытку позже.',
      }
      const error = new Error(messages[response.status] || 'Не удалось выполнить действие. Попробуйте ещё раз.')
      error.status = response.status
      throw error
    }
    if (data.status === 'fallback') throw new Error(data.message || 'AI сейчас недоступен. Вы можете заполнить карточку вручную.')
    return data
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Запрос отменён или занял слишком много времени. Повторите попытку.', { cause: error })
    if (error instanceof TypeError) throw new Error('Не удалось связаться с сервером. Проверьте, что сервер приложения запущен, и повторите попытку.', { cause: error })
    throw error
  } finally {
    clearTimeout(timeout)
    signal?.removeEventListener('abort', abort)
  }
}

export const post = (path, body) => request(path, { method: 'POST', body })

export function rememberChallenge(id) {
  try { localStorage.setItem('ai-sana:challenge:v1', id) } catch { /* In-memory workflow remains usable. */ }
}

export function lastChallenge() {
  try { return localStorage.getItem('ai-sana:challenge:v1') } catch { return null }
}
