import { useEffect, useId, useRef, useState } from 'react'
import { criterionLabels, fields, labels, levelLabels } from './fields'
import { useReducedMotion } from './motion'

export function Notice({ children, success = false }) {
  return children ? <div className={`notice ${success ? 'success' : 'error'}`} role={success ? 'status' : 'alert'}>{children}</div> : null
}

export function Level({ level }) {
  return <span className={`level ${level?.toLowerCase() || 'draft'}`}><span aria-hidden="true">●</span> {levelLabels[level] || 'Не рассчитан'}</span>
}

function ScoreMeter({ score, level, from }) {
  const reduced = useReducedMotion()
  const [display, setDisplay] = useState(from ?? score)
  const currentValue = useRef(from ?? score)
  useEffect(() => {
    let frame
    let start
    if (reduced || from == null) currentValue.current = score
    const origin = currentValue.current
    const tick = (time) => {
      start ??= time
      const elapsed = origin === score ? 1 : Math.min((time - start) / 750, 1)
      // Interpolate only the visual transition; the target is always the API score.
      currentValue.current = elapsed === 1 ? score : Math.round(origin + (score - origin) * (1 - (1 - elapsed) ** 3))
      setDisplay(currentValue.current)
      if (elapsed < 1) frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [score, from, reduced])
  const value = reduced || from == null || from === score ? score : display
  return <>
    <div className="score-heading"><div className="score-number" role="status" aria-label={`Готовность: ${score} из 100`}><strong aria-hidden="true">{value}</strong><span aria-hidden="true"> / 100</span></div><Level level={level} /></div>
    <progress aria-label="Готовность задачи" aria-valuenow={score} value={value} max="100" />
  </>
}

export function ScoreCard({ card, pending = false, audience = 'business', editing = false, animation = { version: 0, from: null } }) {
  const assessed = card && !pending
  return <aside className="panel score-panel" aria-label="Готовность задачи">
    <h2>Готовность задачи</h2>
    {assessed ? <ScoreMeter key={`${card.id}-${animation.version}`} score={card.readiness_score} level={card.readiness_level} from={animation.from} /> : <>
      <div className="score-heading"><div className="score-number"><strong>—</strong><span> / 100</span></div><Level /></div>
      <p className="pending-score">Будет рассчитан после подтверждения карточки.</p>
    </>}
    {assessed && editing && <p className="score-context">Это рейтинг сохранённой карточки. Правки будут учтены после подтверждения.</p>}
    {card ? <>
      {assessed &&
      <dl className="breakdown">{Object.entries(card.breakdown).map(([key, item]) => <div key={key}><dt>{criterionLabels[key] || key}</dt><dd><b>{item.score}</b> / {item.max_score}</dd></div>)}</dl>
      }
      {audience === 'business' && card.missing_information.length > 0 && <details className="recommendations" open>
        <summary>Как повысить готовность</summary>
        {!assessed && <p className="small">Ориентиры по сохранённым полям: ответы и правки ещё не учтены.</p>}
        <ul>{card.recommendations.map((text) => <li key={text}>{text}</li>)}</ul>
        <p className="small">Не хватает: {card.missing_information.map((key) => labels[key] || key).join(', ')}.</p>
      </details>}
    </> : <p className="empty-score">Опишите проблему и уточните детали. После проверки карточки вы увидите её готовность.</p>}
    <p className="score-note">Баллы показывают полноту сохранённой карточки, а не качество идеи.{audience === 'business' && ' Даже задачу с низким рейтингом можно опубликовать.'}</p>
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

export function Modal({ title, children, onClose, busy, returnFocusRef }) {
  const ref = useRef(null)
  const titleId = useId()
  useEffect(() => {
    const dialog = ref.current
    const previousFocus = document.activeElement
    const fallbackFocus = returnFocusRef?.current
    dialog.showModal()
    // Start on the heading: a keyboard user should hear context before acting.
    dialog.querySelector('h2')?.focus()
    return () => {
      dialog.close()
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus()
      else if (fallbackFocus?.isConnected) fallbackFocus.focus()
    }
  }, [returnFocusRef])
  function keepFocus(event) {
    if (event.key !== 'Tab') return
    const controls = [...ref.current.querySelectorAll('button:not(:disabled), input:not(:disabled), a[href], [tabindex="0"]')].filter((element) => element.getClientRects().length > 0)
    if (!controls.length) { event.preventDefault(); return }
    const first = controls[0]
    const last = controls[controls.length - 1]
    if (event.shiftKey && (document.activeElement === first || document.activeElement?.tagName === 'H2')) {
      event.preventDefault(); last.focus()
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault(); first.focus()
    }
  }
  return <dialog ref={ref} className="modal" aria-labelledby={titleId} aria-busy={busy || undefined} onKeyDown={keepFocus} onCancel={(event) => { event.preventDefault(); if (!busy) onClose() }}>
    <h2 id={titleId} tabIndex={-1}>{title}</h2>{children}
  </dialog>
}
