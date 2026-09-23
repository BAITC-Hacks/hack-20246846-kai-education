import { useEffect, useRef, useState } from 'react'
import { post, request, rememberChallenge } from './api'
import { cardFields, labels } from './fields'
import { CardDetails, CardEditor, Modal, Notice, ScoreCard } from './components'
import TeamProposals from './TeamProposals'
import { isReadinessPending, markReadinessPending } from './readinessState'
import { scrollToTop } from './motion'

export default function Business({ initialId, active, busy, setBusy, onCatalog }) {
  const [challenge, setChallenge] = useState(null)
  const [draft, setDraft] = useState('')
  const [phase, setPhase] = useState('draft')
  const [analysis, setAnalysis] = useState(null)
  const [answers, setAnswers] = useState({})
  const [proposal, setProposal] = useState(null)
  const [editor, setEditor] = useState(cardFields)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(Boolean(initialId))
  const [publishModal, setPublishModal] = useState(false)
  const [publicationConsent, setPublicationConsent] = useState(false)
  const [resetModal, setResetModal] = useState(false)
  const [readinessPending, setReadinessPending] = useState(false)
  const [scoreAnimation, setScoreAnimation] = useState({ version: 0, from: null })
  const inFlight = useRef(false)

  useEffect(() => {
    if (!initialId) return
    const controller = new AbortController()
    request(`/challenges/${initialId}`, { signal: controller.signal }).then((card) => {
      if (controller.signal.aborted) return
      setReadinessPending(isReadinessPending(card))
      setChallenge(card); setDraft(card.draft); setEditor(cardFields(card)); setPhase('review')
    }).catch((err) => { if (!controller.signal.aborted) setError(err.message) })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [initialId])

  async function run(action) {
    if (inFlight.current) return
    inFlight.current = true; setBusy(true); setError(''); setSuccess('')
    try { await action() } catch (err) { setError(err.message) }
    finally { inFlight.current = false; setBusy(false) }
  }

  async function analyze() {
    await run(async () => {
      let card = challenge
      if (!card) {
        card = await post('/challenges', { draft: draft.trim() })
        setReadinessPending(true); markReadinessPending(card.id, true)
        setChallenge(card); rememberChallenge(card.id)
      }
      setPhase('interview')
      const result = await post(`/challenges/${card.id}/analysis`)
      setAnalysis(result); setAnswers({})
    })
  }

  async function buildCard(event) {
    event.preventDefault()
    await run(async () => {
      const result = await post(`/challenges/${challenge.id}/card-proposals`, {
        analysis_id: analysis.analysis_id,
        answers: analysis.questions.filter((q) => answers[q.id]?.trim()).map((q) => ({ question_id: q.id, text: answers[q.id].trim() })),
      })
      setProposal(result); setEditor(cardFields(result.proposed_card)); setPhase('card')
      scrollToTop()
    })
  }

  function editManually() {
    setProposal(null); setEditor(cardFields(challenge)); setPhase('card'); setError('')
  }

  async function confirm(event) {
    event.preventDefault()
    await run(async () => {
      const card = proposal
        ? await post(`/challenges/${challenge.id}/card-proposals/${proposal.proposal_id}/confirm`, { confirmed: true, edits: editor })
        : await request(`/challenges/${challenge.id}`, { method: 'PATCH', body: editor })
      setScoreAnimation((previous) => ({ version: previous.version + 1, from: readinessPending ? 0 : challenge.readiness_score }))
      setReadinessPending(false); markReadinessPending(card.id, false)
      setChallenge(card); setProposal(null); setPhase('review')
      setSuccess('Карточка сохранена. Рейтинг пересчитан по заполненным полям.')
      scrollToTop()
    })
  }

  async function publish() {
    await run(async () => {
      const card = await post(`/challenges/${challenge.id}/publish`, { confirmed: true })
      setReadinessPending(false); markReadinessPending(card.id, false)
      setChallenge(card); setPublishModal(false); setPublicationConsent(false)
      setSuccess('Задача опубликована! Теперь студенческие команды могут предложить решение.')
    })
  }

  function reset() {
    setResetModal(false); setReadinessPending(false); setScoreAnimation({ version: 0, from: null })
    setChallenge(null); setDraft(''); setAnalysis(null); setProposal(null); setAnswers({}); setPhase('draft'); setError(''); setSuccess('')
    try { localStorage.removeItem('ai-sana:challenge:v1') } catch { /* Storage is optional. */ }
    scrollToTop()
  }

  const step = { draft: 0, interview: 1, card: 2, review: 3 }[phase]
  const answerCount = Object.values(answers).filter((answer) => answer.trim()).length

  return <section hidden={!active}>
    <div className="page-heading"><h1>От проблемы — к решению</h1><p>Сформулируйте задачу вместе с AI и найдите студенческую команду.</p></div>
    <ol className="steps" aria-label="Этапы подготовки задачи">{['Черновик', 'Вопросы AI', 'Карточка', 'Публикация'].map((name, index) => <li key={name} className={index <= step ? 'current' : ''} aria-current={index === step ? 'step' : undefined}><span>{index < step ? '✓' : index + 1}</span>{name}</li>)}</ol>
    <Notice>{error}</Notice><Notice success>{success}</Notice>
    {loading ? <div className="panel loading" role="status">Загружаем вашу задачу…</div> : <div className="workspace">
      <div className="main-column step-content" key={phase}>
        {phase === 'draft' && <form className="panel draft-panel" onSubmit={(event) => { event.preventDefault(); analyze() }}>
          <h2><label htmlFor="business-draft">Опишите бизнес-проблему</label></h2>
          <p className="intro">Расскажите о ситуации своими словами. AI поможет понять, каких деталей не хватает для команды.</p>
          <textarea id="business-draft" className="draft-input" value={draft} onChange={(event) => setDraft(event.target.value)} required maxLength={20000} disabled={busy} placeholder="Например: у нас небольшой магазин. Менеджеры тратят много времени на одинаковые вопросы клиентов. Хотим упростить обработку обращений." />
          <div className="character-count">{draft.length.toLocaleString('ru-RU')} / 20 000</div>
          <button className="primary" disabled={busy || !draft.trim()}>{busy ? 'Анализируем черновик…' : 'Проанализировать с AI'} <span aria-hidden="true">→</span></button>
          <p className="small under-button">Вы проверяете карточку перед публикацией.</p>
        </form>}
        {phase === 'interview' && <div className="panel">
          <div className="section-heading"><div><h2>Уточним детали</h2><p className="intro">Ответьте на вопросы, чтобы команда лучше поняла вашу задачу.</p></div></div>
          {busy && !analysis && <p className="loading" role="status">AI читает описание и готовит вопросы…</p>}
          {analysis && <form onSubmit={buildCard}>
            <details className="known-info"><summary>Что уже известно из описания</summary><dl>{Object.entries(analysis.known_information).filter(([, value]) => value).map(([key, value]) => <div key={key}><dt>{labels[key]}</dt><dd>{value}</dd></div>)}</dl></details>
            <div className="question-list">{analysis.questions.map((question, index) => <label key={question.id}><span className="question-title"><b>{String(index + 1).padStart(2, '0')}</b>{question.text}</span><textarea data-field={question.field} rows={3} maxLength={10000} placeholder="Ваш ответ. Если данных пока нет, так и напишите." value={answers[question.id] || ''} onChange={(event) => setAnswers({ ...answers, [question.id]: event.target.value })} disabled={busy} /></label>)}</div>
            <p className="small">Отвечено: {answerCount} из {analysis.questions.length}. Можно ответить на часть вопросов; остальные поля останутся пустыми.</p>
            <div className="actions form-actions"><button className="primary" disabled={busy || answerCount === 0}>{busy ? 'Готовим карточку…' : 'Сформировать карточку'} <span aria-hidden="true">→</span></button></div>
          </form>}
          <div className="actions secondary-actions"><button type="button" className="text-button" disabled={busy} onClick={analyze}>Повторить AI-анализ</button><button type="button" className="text-button" disabled={busy} onClick={editManually}>Заполнить вручную</button></div>
        </div>}
        {phase === 'card' && <form className="panel" onSubmit={confirm}>
          <h2>{proposal ? 'AI предлагает — вы проверяете' : 'Редактирование карточки'}</h2>
          <div className="review-callout">{proposal ? 'AI подготовил черновик. Проверьте информацию перед подтверждением. Пока эти изменения не сохранены.' : 'Заполните известные сведения. После сохранения рейтинг пересчитается.'}</div>
          {proposal && <details className="known-info"><summary>Сравнить с сохранённой карточкой</summary><CardDetails card={proposal.current_card} /></details>}
          <CardEditor value={editor} onChange={setEditor} disabled={busy} evidence={proposal?.evidence} />
          <div className="actions form-actions"><button className="primary" disabled={busy}>{busy ? 'Сохраняем…' : 'Подтвердить карточку'}</button><button type="button" className="text-button" disabled={busy} onClick={() => setPhase(proposal ? 'interview' : 'review')}>Назад</button></div>
        </form>}
        {phase === 'review' && challenge && <>
          <article className="panel">
            <div className="section-heading"><div><p className="state-label">{challenge.published ? '✓ Опубликовано' : readinessPending ? 'Черновик сохранён' : 'Карточка подтверждена'}</p><h2>{challenge.title || 'Задача без названия'}</h2></div><button className="text-button" disabled={busy} onClick={editManually}>Редактировать</button></div>
            {challenge.published && <p className="intro">Задача доступна командам в каталоге. Решение о выборе команды принимаете вы.</p>}
            <CardDetails card={challenge} />
            <div className="actions">{challenge.published
              ? <button className="primary" disabled={busy} onClick={onCatalog}>Перейти в каталог <span aria-hidden="true">→</span></button>
              : <button className="primary" disabled={busy} onClick={() => { setPublicationConsent(false); setPublishModal(true) }}>Опубликовать задачу <span aria-hidden="true">→</span></button>}
              <button className="text-button" disabled={busy} onClick={analyze}>Уточнить с AI</button>
            </div>
          </article>
          {challenge.published && <TeamProposals challengeId={challenge.id} active={active} busy={busy} setBusy={setBusy} />}
        </>}
        {challenge && <button className="text-button new-task" disabled={busy} onClick={() => setResetModal(true)}>＋ Создать другую задачу</button>}
      </div>
      <ScoreCard card={challenge} pending={readinessPending} animation={scoreAnimation} editing={phase === 'card' || phase === 'interview'} />
    </div>}
    {phase === 'draft' && <div className="how-it-works"><div><h3>Как это работает?</h3><p>Превратите описание проблемы в понятную задачу для команды.</p></div>{[['Опишите проблему', 'Расскажите о ситуации и желаемом результате.'], ['Уточните детали', 'Ответьте на вопросы AI о недостающих сведениях.'], ['Проверьте и опубликуйте', 'Подтвердите карточку и получите предложения команд.']].map(([title, description], index) => <div className="how-step" key={title}><span>{index + 1}</span><div><h3>{title}</h3><p>{description}</p></div></div>)}</div>}
    {publishModal && <Modal title="Опубликовать задачу?" busy={busy} onClose={() => setPublishModal(false)}>
      <p>Карточка появится в каталоге. Все указанные сведения, включая контакт бизнеса, будут доступны посетителям.</p>
      <label className="consent"><input type="checkbox" checked={publicationConsent} disabled={busy} onChange={(event) => setPublicationConsent(event.target.checked)} />Я проверил(а) карточку и подтверждаю публикацию.</label>
      <Notice>{error}</Notice><div className="actions"><button className="primary" disabled={busy || !publicationConsent} onClick={publish}>{busy ? 'Публикуем…' : 'Подтвердить публикацию'}</button><button disabled={busy} className="text-button" onClick={() => setPublishModal(false)}>Отмена</button></div>
    </Modal>}
    {resetModal && <Modal title="Начать новую задачу?" busy={busy} onClose={() => setResetModal(false)}>
      <p>Сохранённая карточка останется на сервере. Незавершённые ответы и правки будут сброшены.</p>
      <div className="actions"><button className="primary" disabled={busy} onClick={reset}>Начать новую задачу</button><button className="text-button" disabled={busy} onClick={() => setResetModal(false)}>Отмена</button></div>
    </Modal>}
  </section>
}
