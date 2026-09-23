import { useState } from 'react'
import { post } from './api'
import { Modal, Notice } from './components'

export default function AuthPanel({ initialMode = 'login', onClose, onAuthenticated }) {
  const [mode, setMode] = useState(initialMode)
  const [role, setRole] = useState('student')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const registering = mode === 'register'

  function changeMode(next) { setMode(next); setError('') }

  async function submit(event) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const credentials = { email: form.get('email').trim(), password: form.get('password') }
    setError(''); setBusy(true)
    let created = false
    try {
      if (registering) {
        const profile = { ...credentials, name: form.get('name').trim(), role }
        const optional = role === 'student' ? ['university'] : ['company_name', 'position', 'company_industry', 'company_website']
        optional.forEach((key) => { const value = form.get(key)?.trim(); if (value) profile[key] = value })
        await post('/auth/register', profile)
        created = true
      }
      const user = await post('/auth/login', credentials)
      onAuthenticated(user)
    } catch (failure) {
      if (created) {
        setMode('login')
        setError(`Аккаунт создан. Выполните вход. ${failure.message}`)
      } else setError(failure.message)
    } finally { setBusy(false) }
  }

  return <Modal title={registering ? 'Регистрация в KaiBridge AI' : 'Войти в KaiBridge AI'} onClose={onClose} busy={busy}>
    <p>{registering ? 'Выберите свою роль. Данные компании или университета можно указать сейчас.' : 'Войдите, чтобы работать со своими задачами и предложениями.'}</p>
    <div className="auth-tabs" aria-label="Вход или регистрация">
      <button type="button" className={!registering ? 'selected' : ''} aria-pressed={!registering} disabled={busy} onClick={() => changeMode('login')}>Войти</button>
      <button type="button" className={registering ? 'selected' : ''} aria-pressed={registering} disabled={busy} onClick={() => changeMode('register')}>Регистрация</button>
    </div>
    <Notice>{error}</Notice>
    <form key={mode} className="auth-form" onSubmit={submit}>
      {registering && <>
        <fieldset className="auth-role"><legend>Я регистрируюсь как</legend><div className="mode-switch">
          <button type="button" className={role === 'student' ? 'selected' : ''} aria-pressed={role === 'student'} disabled={busy} onClick={() => setRole('student')}>Студент</button>
          <button type="button" className={role === 'business' ? 'selected' : ''} aria-pressed={role === 'business'} disabled={busy} onClick={() => setRole('business')}>Бизнес</button>
        </div></fieldset>
        <label>Имя<input name="name" autoComplete="name" required maxLength={120} disabled={busy} /></label>
      </>}
      <label>Email<input name="email" type="email" autoComplete="email" required maxLength={254} disabled={busy} /></label>
      <label>Пароль<input name="password" type="password" autoComplete={registering ? 'new-password' : 'current-password'} required minLength={8} maxLength={128} disabled={busy} />{registering && <small className="small">От 8 до 128 символов.</small>}</label>
      {registering && (role === 'student'
        ? <label>Университет <span className="muted">(необязательно)</span><input name="university" autoComplete="organization" maxLength={200} disabled={busy} /></label>
        : <>
          <label>Компания <span className="muted">(необязательно)</span><input name="company_name" autoComplete="organization" maxLength={200} disabled={busy} /></label>
          <label>Должность <span className="muted">(необязательно)</span><input name="position" autoComplete="organization-title" maxLength={200} disabled={busy} /></label>
          <label>Отрасль <span className="muted">(необязательно)</span><input name="company_industry" maxLength={200} disabled={busy} /></label>
          <label>Сайт компании <span className="muted">(необязательно)</span><input name="company_website" type="url" autoComplete="url" placeholder="https://example.com" maxLength={2000} disabled={busy} /></label>
        </>)}
      {registering && <p className="small">Регистрация не подтверждает статус студента или компании. Проверка в этой версии — ручной демонстрационный процесс MVP.</p>}
      <div className="actions"><button className="primary" disabled={busy}>{busy ? 'Подождите…' : registering ? 'Создать аккаунт' : 'Войти'}</button><button className="text-button" type="button" disabled={busy} onClick={onClose}>Отмена</button></div>
    </form>
  </Modal>
}
