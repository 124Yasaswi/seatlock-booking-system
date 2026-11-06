import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, rupees, showTime } from '../api'
import Countdown from '../components/Countdown.jsx'

export default function MyBookings() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const keys = useRef({}) // Idempotency-Key per hold

  const load = useCallback(async () => {
    try {
      const [holds, waitlist, bookings] = await Promise.all([api('/holds/me'), api('/waitlist/me'), api('/bookings/me')])
      setData({ holds, waitlist, bookings })
    } catch (e) { setError(e.message) }
  }, [])

  useEffect(() => { load() }, [load])

  const act = async (fn) => {
    setError('')
    try { await fn() } catch (e) { setError(e.message) }
    load()
  }

  if (!data) return error ? <p className="error">{error}</p> : <p className="muted center">Loading…</p>
  const upcoming = data.bookings.filter((b) => b.status === 'confirmed')
  const past = data.bookings.filter((b) => b.status !== 'confirmed')

  return (
    <div className="stack">
      <h1>My bookings</h1>
      {error && <p className="error">{error}</p>}

      {data.holds.length > 0 && (
        <section>
          <h2>Waiting for payment</h2>
          {data.holds.map((h) => {
            keys.current[h.id] ??= crypto.randomUUID()
            return (
              <div key={h.id} className="card booking offer">
                <div>
                  {h.waitlist_id && <span className="badge good">From the waitlist</span>}
                  <h3>{h.title}</h3>
                  <p className="muted">{showTime(h.starts_at)} · Seats {h.seats.join(', ')}</p>
                </div>
                <div className="actions">
                  <Countdown until={h.expires_at} onExpire={load} />
                  <button className="btn primary" onClick={() => act(() => api(`/holds/${h.id}/confirm`, { method: 'POST', headers: { 'Idempotency-Key': keys.current[h.id] } }))}>Pay now</button>
                  <button className="btn" onClick={() => act(() => api(`/holds/${h.id}`, { method: 'DELETE' }))}>Release</button>
                </div>
              </div>
            )
          })}
        </section>
      )}

      {data.waitlist.filter((w) => w.status === 'waiting').length > 0 && (
        <section>
          <h2>Waitlist</h2>
          {data.waitlist.filter((w) => w.status === 'waiting').map((w) => (
            <div key={w.id} className="card booking">
              <div>
                <h3>{w.title}</h3>
                <p className="muted">{showTime(w.starts_at)} · {w.seats_wanted} seat(s) · position #{w.position} in the queue</p>
              </div>
              <button className="btn" onClick={() => act(() => api(`/waitlist/${w.id}`, { method: 'DELETE' }))}>Leave waitlist</button>
            </div>
          ))}
        </section>
      )}

      <section>
        <h2>Upcoming</h2>
        {upcoming.length === 0 && <p className="muted">No bookings yet. <Link to="/">Find a show</Link></p>}
        {upcoming.map((b) => (
          <div key={b.id} className="card booking">
            <div>
              <h3>{b.title}</h3>
              <p className="muted">{showTime(b.starts_at)} · {b.venue}</p>
              <p>Seats <strong>{b.seats.join(', ')}</strong> · {rupees(b.amount_paise)} · #{b.id}</p>
            </div>
            <button className="btn danger" onClick={() => window.confirm('Cancel this booking? The seats go to the waitlist or back on sale.')
              && act(() => api(`/bookings/${b.id}/cancel`, { method: 'POST' }))}>Cancel</button>
          </div>
        ))}
      </section>

      {past.length > 0 && (
        <section>
          <h2>Cancelled</h2>
          {past.map((b) => (
            <div key={b.id} className="card booking dim">
              <div><h3>{b.title}</h3><p className="muted">{showTime(b.starts_at)} · Seats {b.seats.join(', ')}</p></div>
              <span className="badge">Cancelled</span>
            </div>
          ))}
        </section>
      )}
    </div>
  )
}
