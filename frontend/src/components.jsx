import { useEffect, useRef } from 'react'
import { criterionLabels, fields, labels } from './fields'

export function Notice({ children, success = false }) {
  return children ? <div className={`notice ${success ? 'success' : 'error'}`} role={success ? 'status' : 'alert'}>{children}</div> : null
}

export function Level({ level }) {
  return <span className={`level ${level?.toLowerCase() || 'draft'}`}><span aria-hidden="true">●</span> {level || 'Не рассчитан'}</span>
}

export function ScoreCard({ card }) {
  return <aside className="panel score-panel" aria-label="Готовность задачи">
    <h2>Готовность задачи</h2>
    <div className="score-heading"><div className="score-number"><strong>{card?.readiness_score ?? '—'}</strong><span> / 100</span></div><Level level={card?.readiness_level} /></div>
    {card ? <>
      <progress aria-label="Readiness Score" value={card.readiness_score} max="100" />
      <dl className="breakdown">{Object.entries(card.breakdown).map(([key, item]) => <div key={key}><dt>{criterionLabels[key] || key}</dt><dd><b>{item.score}</b> / {item.max_score}</dd></div>)}</dl>
      {card.missing_information.length > 0 && <details className="recommendations" open>
        <summary>Как повысить готовность</summary>
        <ul>{card.recommendations.map((text) => <li key={text}>{text}</li>)}</ul>
        <p className="small">Не хватает: {card.missing_information.map((key) => labels[key] || key).join(', ')}.</p>
      </details>}
    </> : <p className="empty-score">Рейтинг появится после создания черновика. Добавляйте сведения — и следите за готовностью задачи.</p>}
    <p className="score-note">Баллы показывают полноту сохранённой карточки, а не качество идеи. Даже задачу с низким рейтингом можно опубликовать.</p>
  </aside>
}

export function CardEditor({ value, onChange, disabled, evidence }) {
  return <div className="card-editor">{fields.map(([key, label, placeholder]) => <label key={key} className={key === 'title' ? 'full-width' : ''}>
    <span>{label}</span>
    {['title', 'contact', 'industry'].includes(key)
      ? <input aria-label={label} name={key} value={value[key]} maxLength={10000} placeholder={placeholder} disabled={disabled} onChange={(event) => onChange({ ...value, [key]: event.target.value })} />
      : <textarea aria-label={label} name={key} value={value[key]} maxLength={10000} rows={3} placeholder={placeholder} disabled={disabled} onChange={(event) => onChange({ ...value, [key]: event.target.value })} />}
    {evidence?.[key] && <small className="source">Источник: {evidence[key].source_id === 'draft' ? 'исходное описание' : 'ответ бизнеса'}</small>}
  </label>)}</div>
}

export function CardDetails({ card }) {
  return <dl className="card-details">{fields.filter(([key]) => key !== 'title').map(([key, label]) => <div key={key}><dt>{label}</dt><dd>{card[key] || <span className="muted">Пока не указано</span>}</dd></div>)}</dl>
}

export function Modal({ title, children, onClose, busy }) {
  const ref = useRef(null)
  useEffect(() => {
    const dialog = ref.current
    dialog.showModal()
    return () => dialog.close()
  }, [])
  return <dialog ref={ref} className="modal" aria-labelledby="modal-title" onCancel={(event) => { event.preventDefault(); if (!busy) onClose() }}>
    <h2 id="modal-title">{title}</h2>{children}
  </dialog>
}
