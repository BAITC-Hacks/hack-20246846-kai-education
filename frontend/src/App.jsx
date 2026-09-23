import { useCallback, useEffect, useState } from 'react'
import Business from './Business'
import Catalog from './Catalog'
import AuthPanel from './AuthPanel'
import { Notice } from './components'
import { forgetChallenge, lastChallenge, post, rememberChallenge, request } from './api'
import './App.css'

const verificationLabels = { unverified: 'Неподтверждён', pending: 'На проверке', verified: 'Подтверждён', rejected: 'Проверка отклонена' }

export default function App() {
  const [user, setUser] = useState(null)
  const [loadingAuth, setLoadingAuth] = useState(true)
  const [authMode, setAuthMode] = useState(null)
  const [authBusy, setAuthBusy] = useState(false)
  const [authError, setAuthError] = useState('')
  const [page, setPage] = useState('catalog')
  const [busy, setBusy] = useState(false)
  const [businessId, setBusinessId] = useState(null)
  const [workspaceKey, setWorkspaceKey] = useState(0)
  const [aiMode, setAiMode] = useState({ provider: null, error: '' })
  const mode = user?.role || 'student'
  const locked = busy || authBusy || loadingAuth

  const applyUser = useCallback((next) => {
    setUser(next)
    setBusinessId(next?.role === 'business' ? lastChallenge(next.id) : null)
    setWorkspaceKey((value) => value + 1)
    setBusy(false)
    setPage(next?.role === 'business' ? 'business' : 'catalog')
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    request('/health', { signal: controller.signal }).then((health) => {
      if (controller.signal.aborted) return
      if (!['demo', 'openai'].includes(health.ai_provider)) throw new Error('Не удалось определить режим AI. Обновите страницу после проверки backend.')
      setAiMode({ provider: health.ai_provider, error: '' })
    }).catch((error) => {
      if (!controller.signal.aborted) setAiMode({ provider: null, error: error.message })
    })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    request('/auth/me', { signal: controller.signal }).then((next) => {
      if (!controller.signal.aborted) applyUser(next)
    }).catch((error) => {
      if (controller.signal.aborted) return
      applyUser(null)
      if (error.status !== 401) setAuthError(error.message)
    }).finally(() => { if (!controller.signal.aborted) setLoadingAuth(false) })
    return () => controller.abort()
  }, [applyUser])

  function authenticated(next) { applyUser(next); setAuthMode(null); setAuthError('') }
  function manage(id) {
    if (user?.role !== 'business') return
    rememberChallenge(id, user.id); setBusinessId(id); setWorkspaceKey((value) => value + 1); setPage('business')
  }
  async function logout() {
    setAuthError(''); setAuthBusy(true)
    try { await post('/auth/logout'); forgetChallenge(user.id); applyUser(null) }
    catch (error) { setAuthError(error.message) }
    finally { setAuthBusy(false) }
  }
  async function verification(action) {
    setAuthError(''); setAuthBusy(true)
    try {
      const next = action === 'request' ? await post('/auth/request-verification') : await request('/auth/me')
      if (next.id !== user.id) applyUser(next)
      else setUser(next)
    } catch (error) {
      if (error.status === 401) { forgetChallenge(user.id); applyUser(null) }
      setAuthError(error.message)
    } finally { setAuthBusy(false) }
  }

  return <>
    <a className="skip-link" href="#main">К содержимому</a>
    <header className="app-header"><div className="header-inner">
      <div className="brand"><strong>KaiBridge AI</strong><span>by Kai Education AI</span></div>
      <nav aria-label="Основная навигация">
        {user?.role === 'business' && <button className={page === 'business' ? 'active' : ''} disabled={locked} onClick={() => setPage('business')}>Моя задача</button>}
        <button className={page === 'catalog' ? 'active' : ''} disabled={locked} onClick={() => setPage('catalog')}>Каталог задач</button>
        {!user && <button disabled={locked} onClick={() => setAuthMode('login')}>Бизнесу</button>}
      </nav>
      {loadingAuth ? <span className="small" role="status">Проверяем вход…</span> : user ? <div className="account-controls">
        <div className="account-summary"><strong title={user.name}>{user.name}</strong><span>{user.role === 'business' ? 'Бизнес' : 'Студент'}</span><span className={`verification-badge ${user.verification_status}`}>{verificationLabels[user.verification_status]}</span></div>
        <button className="text-button" disabled={locked} onClick={logout}>Выйти</button>
      </div> : <div className="account-controls"><button className="text-button" disabled={locked} onClick={() => setAuthMode('login')}>Войти</button><button className="primary" disabled={locked} onClick={() => setAuthMode('register')}>Регистрация</button></div>}
    </div></header>
    <main id="main" className="app-main">
      {aiMode.provider === 'demo' && <section className="demo-ai-banner" aria-label="Демонстрационный AI-режим">
        <strong>Демонстрационный AI-режим</strong>
        <p>Используется локальный воспроизводимый provider для технической проверки. Ответы формируются детерминированно, без LLM. Реальная интеграция работает через OpenAI GPT-5.4-mini.</p>
      </section>}
      {!aiMode.provider && !aiMode.error && <p className="small" role="status">Проверяем режим AI…</p>}
      <Notice>{aiMode.error}</Notice>
      <Notice>{authError}</Notice>
      {user && <section className="identity-strip" aria-label="Статус подтверждения аккаунта">
        <div><strong>{verificationLabels[user.verification_status]}</strong><p>{user.verification_status === 'verified'
          ? 'Демонстрационное подтверждение MVP получено. Это не автоматическая проверка документов или компании.'
          : user.verification_status === 'pending'
            ? 'Заявка отправлена. В MVP статус меняется вручную организатором демо; документы и компании автоматически не проверяются.'
            : user.verification_status === 'rejected'
              ? 'Демонстрационная проверка отклонена. Обратитесь к организатору демо.'
              : `Для ${user.role === 'business' ? 'публикации задачи и выбора команды' : 'отправки предложения'} нужно подтверждение. В MVP это ручная демонстрационная проверка.`}</p></div>
        <div className="identity-actions">{user.verification_status === 'unverified' && <button className="text-button" disabled={locked} onClick={() => verification('request')}>Запросить проверку</button>}<button className="text-button" disabled={locked} onClick={() => verification('refresh')}>{authBusy ? 'Подождите…' : 'Обновить статус'}</button></div>
      </section>}
      {loadingAuth ? <p className="loading" role="status">Загружаем приложение…</p> : <>
        {user?.role === 'business' && <Business key={`${user.id}-${businessId}-${workspaceKey}`} user={user} onRequireAuth={() => setAuthMode('login')} initialId={businessId} active={page === 'business'} busy={busy} setBusy={setBusy} onCatalog={() => setPage('catalog')} />}
        {page === 'catalog' && <Catalog key={user?.id || 'guest'} user={user} onRequireAuth={() => setAuthMode('login')} mode={mode} busy={busy} setBusy={setBusy} onManage={manage} />}
      </>}
    </main>
    <footer className="app-footer"><span>KaiBridge AI</span><span>Реальные задачи бизнеса. Решения студенческих команд.</span></footer>
    {authMode && <AuthPanel initialMode={authMode} onClose={() => setAuthMode(null)} onAuthenticated={authenticated} />}
  </>
}
