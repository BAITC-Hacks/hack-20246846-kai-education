import { useEffect, useRef, useState } from 'react'
import { post, request } from './api'
import { levels, levelLabels } from './fields'
import { CardDetails, Level, Notice, ScoreCard } from './components'
import { scrollToSection, scrollToTop } from './motion'

const proposalFields = [
  ['team_name', 'Название команды', 200], ['skills', 'Навыки команды', 10000],
  ['solution_idea', 'Идея решения', 10000], ['plan', 'План работы', 10000],
  ['estimated_time', 'Оценка сроков', 500], ['prototype_url', 'Ссылка на прототип (необязательно)', 2000],
]

function StudentProposal({ challengeId, busy, setBusy, user, ownerId, onRequireAuth }) {
  const [open, setOpen] = useState(false)
  const [sent, setSent] = useState(false)
  const [form, setForm] = useState(Object.fromEntries(proposalFields.map(([key]) => [key, ''])))
  const [error, setError] = useState('')
  const lock = useRef(false)
  const restriction = !ownerId
    ? 'Это архивная задача без владельца. Приём предложений станет доступен после назначения владельца организатором демо.'
    : user && user.role !== 'student'
      ? 'Предложения отправляют пользователи с ролью «Студент».'
      : user && user.verification_status !== 'verified'
        ? 'Для отправки предложения нужен подтверждённый студенческий аккаунт. Запросите проверку в верхней части страницы.'
        : ''
  function start() {
    if (!user) { onRequireAuth(); return }
    if (restriction) { setError(restriction); return }
    setError(''); setOpen(true)
  }
  async function submit(event) {
    event.preventDefault()
    if (!user) { onRequireAuth(); return }
    if (restriction) { setError(restriction); return }
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    try {
      await post(`/challenges/${challengeId}/proposals`, { ...Object.fromEntries(Object.entries(form).map(([key, value]) => [key, value.trim()])), prototype_url: form.prototype_url.trim() || null })
      setSent(true); setOpen(false)
    } catch (err) { setError(err.message) }
    finally { lock.current = false; setBusy(false) }
  }
  if (sent) return <div className="panel sent-state" role="status"><span className="success-mark">✓</span><h2>Предложение отправлено</h2><p>Бизнес получил вашу заявку и вручную примет решение. Сейчас статус: «Ожидает решения».</p></div>
  return <section className="panel"><h2>Готовы предложить решение?</h2><p className="intro">Расскажите о команде и подходе к задаче. Бизнес самостоятельно выберет предложение.</p>
    <Notice>{error}</Notice>
    {!open ? <button className="primary" disabled={busy} onClick={start}>Предложить решение <span aria-hidden="true">→</span></button> : <form onSubmit={submit}>
      <div className="card-editor">{proposalFields.map(([key, label, max]) => <label key={key} className={['solution_idea', 'plan'].includes(key) ? 'full-width' : ''}><span>{label}</span>
        {['solution_idea', 'plan', 'skills'].includes(key)
          ? <textarea name={key} rows={3} value={form[key]} maxLength={max} required disabled={busy} onChange={(event) => setForm({ ...form, [key]: event.target.value })} />
          : <input name={key} type={key === 'prototype_url' ? 'url' : 'text'} pattern={key === 'prototype_url' ? 'https?://.+' : undefined} placeholder={key === 'prototype_url' ? 'https://' : ''} value={form[key]} maxLength={max} required={key !== 'prototype_url'} disabled={busy} onChange={(event) => setForm({ ...form, [key]: event.target.value })} />}
      </label>)}</div><div className="actions form-actions"><button className="primary" disabled={busy || proposalFields.some(([key]) => key !== 'prototype_url' && !form[key].trim())}>{busy ? 'Отправляем…' : 'Отправить предложение'}</button><button type="button" className="text-button" disabled={busy} onClick={() => setOpen(false)}>Отмена</button></div>
    </form>}
  </section>
}

export default function Catalog({ mode, busy, setBusy, onManage, user, onRequireAuth }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [filter, setFilter] = useState({ industry: '', readiness_level: '' })
  const [query, setQuery] = useState({ industry: '', readiness_level: '' })
  const [selected, setSelected] = useState(null)
  const [version, setVersion] = useState(0)
  const selectionRequest = useRef(0)

  useEffect(() => {
    const controller = new AbortController()
    const params = new URLSearchParams(Object.entries(query).filter(([, value]) => value))
    request(`/challenges?${params}`, { signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) { setItems(data); setError('') }
    }).catch((err) => { if (!controller.signal.aborted) setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [query, version])

  async function open(card) {
    const ticket = ++selectionRequest.current
    setBusy(true); setError('')
    try {
      const data = await request(`/challenges/${card.id}`)
      if (ticket === selectionRequest.current) { setSelected(data); scrollToTop() }
    } catch (err) { setError(err.message) }
    finally { setBusy(false) }
  }

  if (selected) return <section>
    <button className="text-button back-button" disabled={busy} onClick={() => setSelected(null)}>← Все задачи</button>
    <div className="detail-heading"><span className="industry-label">{selected.industry || 'Отрасль не указана'}</span><h1>{selected.title || 'Задача без названия'}</h1>{mode === 'student' && <button className="primary detail-cta" disabled={busy} onClick={() => { const section = document.getElementById('student-proposal'); scrollToSection(section); (section?.querySelector('button:not(:disabled), input:not(:disabled), textarea:not(:disabled)') || section)?.focus({ preventScroll: true }) }}>Перейти к отклику ↓</button>}</div>
    <Notice>{error}</Notice><div className="workspace"><div className="main-column"><article className="panel"><h2>О задаче</h2><CardDetails card={selected} /></article>
      {user?.role !== 'business' ? <div id="student-proposal" tabIndex={-1}><StudentProposal key={`${selected.id}:${user?.id || 'guest'}`} challengeId={selected.id} ownerId={selected.owner_id} user={user} onRequireAuth={onRequireAuth} busy={busy} setBusy={setBusy} /></div> : selected.owner_id === user.id ? <div className="panel"><h2>Работа с задачей</h2><p className="intro">Просматривайте заявки команд и принимайте решение в режиме «Бизнес».</p><button className="primary" disabled={busy} onClick={() => onManage(selected.id)}>Управлять задачей</button></div> : <div className="panel"><p className="intro">Управлять этой задачей может только её владелец. Предложения отправляют подтверждённые студенческие аккаунты.</p></div>}
    </div><ScoreCard card={selected} audience={mode} /></div>
  </section>

  return <section>
    <div className="page-heading catalog-heading"><h1>Задачи, которым нужно решение</h1><p>Найдите реальную бизнес-задачу и предложите подход своей команды.</p></div>
    <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); setLoading(true); setQuery({ industry: filter.industry.trim(), readiness_level: filter.readiness_level }); setVersion((value) => value + 1) }}>
      <label><span>Отрасль</span><input aria-describedby="industry-filter-hint" value={filter.industry} onChange={(event) => setFilter({ ...filter, industry: event.target.value })} placeholder="Все отрасли" disabled={busy} /></label>
      <label><span>Готовность задачи</span><select value={filter.readiness_level} disabled={busy} onChange={(event) => setFilter({ ...filter, readiness_level: event.target.value })}><option value="">Все уровни</option>{levels.map((level) => <option key={level} value={level}>{levelLabels[level]}</option>)}</select></label>
      <button className="primary" disabled={busy || loading}>Применить фильтры</button><button type="button" className="text-button" disabled={busy || loading} onClick={() => { setFilter({ industry: '', readiness_level: '' }); setQuery({ industry: '', readiness_level: '' }); setLoading(true); setVersion((value) => value + 1) }}>Сбросить</button>
    </form>
    <p className="small" id="industry-filter-hint">Отрасль ищется по точному названию, без учёта регистра.</p>
    <Notice>{error}</Notice>
    <div className="catalog-meta"><span>{loading ? 'Загружаем задачи…' : `Опубликовано: ${items.length}`}</span><span>По готовности: сначала высокий рейтинг</span><button className="text-button" disabled={busy || loading} onClick={() => { setLoading(true); setVersion((value) => value + 1) }}>Обновить</button></div>
    {loading ? <div className="panel loading" role="status">Загружаем каталог…</div> : items.length === 0 ? <div className="panel empty-state"><h2>{query.industry || query.readiness_level ? 'По этим фильтрам задач пока нет' : 'Каталог пока пуст'}</h2><p>{query.industry || query.readiness_level ? 'Сбросьте фильтры или укажите точное название отрасли.' : 'Опубликуйте задачу в режиме «Бизнес» — она появится здесь.'}</p></div> : <div className="catalog-list">{items.map((card) => <article className="catalog-card" key={card.id}>
      <div className="catalog-copy"><span className="industry-label">{card.industry || 'Отрасль не указана'}</span><h2><button className="title-button" disabled={busy} onClick={() => open(card)}>{card.title || 'Задача без названия'}</button></h2><p>{card.context || card.need || card.draft}</p></div>
      <div className="catalog-score"><div><strong>{card.readiness_score}</strong><span> / 100</span></div><Level level={card.readiness_level} /><button className="text-button" disabled={busy} onClick={() => open(card)}>Открыть задачу →</button></div>
    </article>)}</div>}
  </section>
}
