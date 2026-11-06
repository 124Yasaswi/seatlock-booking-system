import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, rupees, seatSocket, showTime } from '../api'
import { useAuth } from '../auth.jsx'
import Countdown from '../components/Countdown.jsx'
import SeatMap from '../components/SeatMap.jsx'

export default function SeatPage() {
  const { id } = useParams()
  const { user } = useAuth()
  const navigate = useNavigate()
  const [show, setShow] = useState(null)
  const [selected, setSelected] = useState(new Set())
  const [hold, setHold] = useState(null)        // my current hold
  const [booking, setBooking] = useState(null)  // set after paying
  const [count, setCount] = useState(2)
  const [message, setMessage] = useState(null)  // { kind: 'error'|'info', text, waitlist? }
  const [busy, setBusy] = useState(false)
  const payKey = useRef(null)                   // one Idempotency-Key per hold

  const load = useCallback(() => api(`/shows/${id}`).then(setShow).catch((e) => setMessage({ kind: 'error', text: e.message })), [id])

  useEffect(() => { load() }, [load])

  // Live updates: other people's holds and bookings appear without refreshing.
  useEffect(() => seatSocket(id, (msg) => {
    if (msg.type !== 'seats') return
    const changed = new Map(msg.seats.map((s) => [s.seat_id, s.status]))
    setShow((prev) => prev && { ...prev, seats: prev.seats.map((s) => (changed.has(s.id) ? { ...s, status: changed.get(s.id) } : s)) })
    setSelected((prev) => new Set([...prev].filter((sid) => !changed.has(sid) || changed.get(sid) === 'available')))
  }), [id])

  const mine = new Set(hold ? hold.seats.map((s) => s.seat_id) : [])
  const needLogin = () => { if (!user) { navigate('/login'); return true } return false }

  const run = async (fn) => {
    setBusy(true)
    setMessage(null)
    try { await fn() } catch (e) { handleError(e) } finally { setBusy(false) }
  }

  const handleError = (e) => {
    if (e.code === 'seats_taken') {
      setMessage({ kind: 'error', text: 'Someone just took one of those seats. Pick again.' })
      setSelected(new Set())
      load()
    } else if (e.code === 'no_block') {
      setMessage({ kind: 'info', text: e.message, waitlist: true })
    } else if (e.code === 'hold_expired') {
      setHold(null)
      setMessage({ kind: 'error', text: 'Your 5 minutes ran out and the seats were released.' })
      load()
    } else {
      setMessage({ kind: 'error', text: e.message })
    }
  }

  const gotHold = (h) => {
    setHold(h)
    setSelected(new Set())
    payKey.current = crypto.randomUUID()
  }

  const toggle = (seatId) => {
    const next = new Set(selected)
    if (next.has(seatId)) next.delete(seatId)
    else if (next.size < 10) next.add(seatId)
    setSelected(next)
  }

  const holdSelected = () => !needLogin() && run(async () => {
    gotHold(await api(`/shows/${id}/holds`, { method: 'POST', body: { seat_ids: [...selected] } }))
  })

  const holdBest = () => !needLogin() && run(async () => {
    gotHold(await api(`/shows/${id}/holds/best`, { method: 'POST', body: { count } }))
  })

  const release = () => run(async () => {
    await api(`/holds/${hold.id}`, { method: 'DELETE' })
    setHold(null)
  })

  const pay = () => run(async () => {
    // The same key is sent on every retry, so a double click can never book twice.
    const b = await api(`/holds/${hold.id}/confirm`, { method: 'POST', headers: { 'Idempotency-Key': payKey.current } })
    setBooking(b)
    setHold(null)
  })

  const joinWaitlist = () => !needLogin() && run(async () => {
    await api(`/shows/${id}/waitlist`, { method: 'POST', body: { seats_wanted: count } })
    setMessage({ kind: 'info', text: `You're on the waitlist for ${count} seat(s). If seats free up, we hold them for you. Check My bookings.` })
  })

  if (!show) return message ? <p className="error">{message.text}</p> : <p className="muted center">Loading seats…</p>

  if (booking) {
    return (
      <div className="card success">
        <div className="tick" aria-hidden>✓</div>
        <h2>You're booked!</h2>
        <p><strong>{booking.title}</strong> · {showTime(booking.starts_at)} · {booking.venue}</p>
        <p className="seats-list">Seats {booking.seats.join(', ')}</p>
        <p>Paid {rupees(booking.amount_paise)} · Booking #{booking.id}</p>
        <div className="row-gap center-row">
          <Link to="/me" className="btn primary">My bookings</Link>
          <Link to="/" className="btn">More shows</Link>
        </div>
      </div>
    )
  }

  const free = show.seats.filter((s) => s.status === 'available').length
  const selectedTotal = show.seats.filter((s) => selected.has(s.id))
    .reduce((t, s) => t + (s.category === 'premium' ? show.premium_price_paise : show.regular_price_paise), 0)

  return (
    <div className="seat-page">
      <div className="show-head">
        <div>
          <h1>{show.title}</h1>
          <p className="muted">{show.venue}, {show.city} · {showTime(show.starts_at)}</p>
        </div>
        <span className={free ? 'badge' : 'badge danger'}>{free ? `${free} ${free === 1 ? 'seat' : 'seats'} free` : 'Sold out'}</span>
      </div>

      <div className="layout">
        <div className="card map-card">
          <SeatMap seats={show.seats} selected={selected} mine={mine} onToggle={toggle} disabled={!!hold || busy} />
          <div className="legend">
            <span><i className="seat-dot available" /> Free</span>
            <span><i className="seat-dot selected" /> Selected</span>
            <span><i className="seat-dot mine" /> Your hold</span>
            <span><i className="seat-dot held" /> Held by someone</span>
            <span><i className="seat-dot booked" /> Booked</span>
            <span><i className="seat-dot available premium" /> Premium {rupees(show.premium_price_paise)}</span>
            <span className="muted">Regular {rupees(show.regular_price_paise)}</span>
          </div>
        </div>

        <aside className="card panel">
          {message && (
            <div className={message.kind === 'error' ? 'note error-note' : 'note'}>
              <p>{message.text}</p>
              {message.waitlist && <button className="btn" onClick={joinWaitlist} disabled={busy}>Join waitlist for {count}</button>}
            </div>
          )}

          {hold ? (
            <>
              <h3>Seats held for you</h3>
              <p className="muted">Pay before the timer ends, or they go back to everyone.</p>
              <div className="timer-box"><Countdown until={hold.expires_at} onExpire={() => handleError({ code: 'hold_expired' })} /></div>
              <ul className="hold-list">
                {hold.seats.map((s) => (
                  <li key={s.seat_id}><span>{s.label} <small className="muted">{s.category}</small></span><span>{rupees(s.price_paise)}</span></li>
                ))}
              </ul>
              <div className="row-between total"><span>Total</span><strong>{rupees(hold.amount_paise)}</strong></div>
              <button className="btn primary wide" onClick={pay} disabled={busy}>{busy ? 'Paying…' : `Pay ${rupees(hold.amount_paise)}`}</button>
              <button className="btn wide" onClick={release} disabled={busy}>Release seats</button>
              <p className="muted small">Payment is simulated in this demo.</p>
            </>
          ) : (
            <>
              <h3>Find the best seats</h3>
              <p className="muted">We pick seats together, as close to the centre as possible.</p>
              <div className="row-gap">
                <select value={count} onChange={(e) => setCount(Number(e.target.value))} aria-label="Number of seats">
                  {Array.from({ length: 10 }, (_, i) => i + 1).map((n) => <option key={n} value={n}>{n} {n === 1 ? 'seat' : 'seats'}</option>)}
                </select>
                <button className="btn primary" onClick={holdBest} disabled={busy}>Find best {count}</button>
              </div>
              {free === 0 && <button className="btn wide" onClick={joinWaitlist} disabled={busy}>Join the waitlist</button>}

              <hr />
              <h3>Or pick seats yourself</h3>
              {selected.size === 0
                ? <p className="muted">Tap free seats on the map (up to 10).</p>
                : <>
                    <p>{selected.size} selected · {rupees(selectedTotal)}</p>
                    <button className="btn primary wide" onClick={holdSelected} disabled={busy}>Hold {selected.size} {selected.size === 1 ? 'seat' : 'seats'} for 5 min</button>
                    <button className="btn wide" onClick={() => setSelected(new Set())}>Clear</button>
                  </>}
            </>
          )}
        </aside>
      </div>
    </div>
  )
}
