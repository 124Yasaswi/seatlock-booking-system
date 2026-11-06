import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth.jsx'

// Demo accounts that exist in the seeded demo database.
const DEMO = { user: ['demo@seatlock.test', 'Demo@1234'], admin: ['admin@seatlock.test', 'Admin@1234'] }

export default function Login() {
  const { login, register } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState('login')
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value })

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const user = mode === 'login'
        ? await login(form.email, form.password)
        : await register(form.name, form.email, form.password)
      navigate(user.role === 'admin' ? '/admin' : '/')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth card">
      <div className="tabs">
        <button className={mode === 'login' ? 'active' : ''} onClick={() => setMode('login')}>Sign in</button>
        <button className={mode === 'register' ? 'active' : ''} onClick={() => setMode('register')}>Create account</button>
      </div>
      <form onSubmit={submit}>
        {mode === 'register' && (
          <label>Name<input value={form.name} onChange={set('name')} required maxLength={60} /></label>
        )}
        <label>Email<input type="email" value={form.email} onChange={set('email')} required autoComplete="email" /></label>
        <label>Password
          <input type="password" value={form.password} onChange={set('password')} required minLength={mode === 'register' ? 8 : 1}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
        </label>
        {error && <p className="error">{error}</p>}
        <button className="btn primary wide" disabled={busy}>{busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}</button>
      </form>
      {mode === 'login' && (
        <div className="demo">
          <p className="muted small">Just looking around? Use a demo account:</p>
          <div className="row-gap">
            <button className="btn" onClick={() => setForm({ ...form, email: DEMO.user[0], password: DEMO.user[1] })}>Demo user</button>
            <button className="btn" onClick={() => setForm({ ...form, email: DEMO.admin[0], password: DEMO.admin[1] })}>Demo admin</button>
          </div>
        </div>
      )}
    </div>
  )
}
