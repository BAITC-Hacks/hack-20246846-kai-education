import { useEffect, useRef, useState } from 'react'
import { post, request } from './api'
import { Modal, Notice } from './components'

const statusLabels = { pending: 'Ожидает решения', accepted: 'Принято', rejected: 'Отклонено' }

export default function TeamProposals({ challengeId, active, busy, setBusy }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [version, setVersion] = useState(0)
  const [decision, setDecision] = useState(null)
  const [decisionError, setDecisionError] = useState('')
  const deciding = useRef(false)
  const headingRef = useRef(null)
  useEffect(() => {
    if (!active) return
    const controller = new AbortController()
    request(`/challenges/${challengeId}/proposals`, { signal: controller.signal }).then((data) => {
      if (!controller.signal.aborted) { setItems(data); setError('') }
    }).catch((err) => { if (!controller.signal.aborted) setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [challengeId, active, version])

  async function decide(item, action) {
    if (busy || deciding.current) return
    deciding.current = true
    setBusy(true); setError(''); setDecisionError(''); setSuccess('')
    try {
      const result = await post(`/challenges/${challengeId}/proposals/${item.id}/${action}`)
      setItems((current) => current.map((proposal) => proposal.id === result.id ? result : proposal))
      setSuccess(action === 'accept' ? 'Команда выбрана. Предложение принято.' : 'Предложение отклонено.')
      setDecision(null)
    } catch (err) { setError(err.message); setDecisionError(err.message); setVersion((value) => value + 1) }
    finally { deciding.current = false; setBusy(false) }
  }

  const hasAccepted = items.some((item) => item.status === 'accepted')
  return <section className="panel team-section"><div className="section-heading"><h2 ref={headingRef} tabIndex={-1}>Предложения команд</h2><button className="text-button" disabled={busy || loading} onClick={() => { setLoading(true); setVersion((value) => value + 1) }}>Обновить</button></div>
    <p className="intro">Выберите одну команду вручную. AI не оценивает и не ранжирует предложения.</p>
    <Notice>{error}</Notice><Notice success>{success}</Notice>
    {loading ? <p role="status">Загружаем предложения…</p> : items.length === 0 ? <div className="empty-state"><h3>Пока нет предложений</h3><p>Команды смогут откликнуться на задачу в режиме «Студент».</p></div> : <div className="team-list">{items.map((item) => <article className="team-card" key={item.id}>
      <div className="section-heading"><h3>{item.team_name}</h3><span className={`proposal-status ${item.status}`}>{statusLabels[item.status]}</span></div>
      <dl className="card-details">{[['skills', 'Навыки'], ['solution_idea', 'Идея решения'], ['plan', 'План работы'], ['estimated_time', 'Оценка сроков']].map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{item[key]}</dd></div>)}</dl>
      {item.prototype_url && <a href={item.prototype_url} target="_blank" rel="noopener noreferrer" className="prototype-link">Посмотреть прототип ↗</a>}
      {item.status === 'pending' && <div className="actions"><button className="primary" disabled={busy || hasAccepted} onClick={() => { setDecisionError(''); setDecision({ item, action: 'accept' }) }}>Принять</button><button className="danger-button" disabled={busy} onClick={() => { setDecisionError(''); setDecision({ item, action: 'reject' }) }}>Отклонить</button></div>}
    </article>)}</div>}
    {hasAccepted && <p className="small">Команда уже выбрана. Остальные заявки остаются в ожидании; их можно отклонить.</p>}
    {decision && <Modal title={decision.action === 'accept' ? 'Принять предложение?' : 'Отклонить предложение?'} busy={busy} onClose={() => setDecision(null)} returnFocusRef={headingRef}>
      <p>Команда «{decision.item.team_name}». {decision.action === 'accept' ? 'Для задачи можно выбрать только одну команду.' : 'Предложение получит статус «Отклонено».'} Отменить это решение в приложении нельзя.</p>
      <Notice>{decisionError}</Notice>
      <div className="actions"><button className={decision.action === 'accept' ? 'primary' : 'danger-button'} disabled={busy} onClick={() => decide(decision.item, decision.action)}>{busy ? 'Сохраняем…' : decision.action === 'accept' ? 'Подтвердить принятие' : 'Подтвердить отклонение'}</button><button className="text-button" disabled={busy} onClick={() => setDecision(null)}>Отмена</button></div>
    </Modal>}
  </section>
}
