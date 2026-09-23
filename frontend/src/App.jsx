import { useState } from 'react'
import Business from './Business'
import Catalog from './Catalog'
import { lastChallenge, rememberChallenge } from './api'
import './App.css'

export default function App() {
  const [mode, setMode] = useState('business')
  const [page, setPage] = useState('business')
  const [busy, setBusy] = useState(false)
  const [businessId, setBusinessId] = useState(lastChallenge)
  const [workspaceKey, setWorkspaceKey] = useState(0)
  function changeMode(next) { setMode(next); setPage(next === 'student' ? 'catalog' : 'business') }
  function manage(id) { rememberChallenge(id); setBusinessId(id); setWorkspaceKey((value) => value + 1); setPage('business'); setMode('business') }
  return <>
    <a className="skip-link" href="#main">К содержимому</a>
    <header className="app-header"><div className="header-inner">
      <div className="brand"><strong>KaiBridge AI</strong><span>by Kai Education AI</span></div>
      <nav aria-label="Основная навигация">
        {mode === 'business' && <button className={page === 'business' ? 'active' : ''} disabled={busy} onClick={() => setPage('business')}>Моя задача</button>}
        <button className={page === 'catalog' ? 'active' : ''} disabled={busy} onClick={() => setPage('catalog')}>Каталог задач</button>
      </nav>
      <div className="mode-switch" aria-label="Режим работы">{['business', 'student'].map((item) => <button key={item} aria-pressed={mode === item} className={mode === item ? 'selected' : ''} disabled={busy} onClick={() => changeMode(item)}>{item === 'business' ? 'Бизнес' : 'Студент'}</button>)}</div>
    </div></header>
    <main id="main" className="app-main">
      <Business key={`${businessId}-${workspaceKey}`} initialId={businessId} active={page === 'business'} busy={busy} setBusy={setBusy} onCatalog={() => setPage('catalog')} />
      {page === 'catalog' && <Catalog mode={mode} busy={busy} setBusy={setBusy} onManage={manage} />}
    </main>
    <footer className="app-footer"><span>KaiBridge AI</span><span>Реальные задачи бизнеса. Решения студенческих команд.</span></footer>
  </>
}
