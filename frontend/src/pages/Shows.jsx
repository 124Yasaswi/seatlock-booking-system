import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, rupees, showTime } from '../api'

export default function Shows() {
  const [shows, setShows] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api('/shows').then(setShows).catch((e) => setError(e.message))
  }, [])

  if (error) return <p className="error">{error}</p>
  if (!shows) return <p className="muted center">Loading shows…</p>

  return (
    <>
      <section className="hero">
        <h1>Book your seats. Nobody else can take them.</h1>
        <p className="muted">Live seat maps, a 5-minute seat hold while you pay, and a waitlist for sold-out shows.</p>
      </section>
      <div className="grid">
        {shows.map((s) => {
          const pct = Math.round(100 * (1 - s.seats_free / s.seats_total))
          const soldOut = s.seats_free === 0
          return (
            <Link key={s.id} to={`/shows/${s.id}`} className="card show-card">
              <div className="poster" data-title={s.title}>{s.title.split(' ').map((w) => w[0]).join('')}</div>
              <div className="show-body">
                <h3>{s.title}</h3>
                <p className="muted">{s.venue}, {s.city}</p>
                <p>{showTime(s.starts_at)}</p>
                <div className="fill" title={`${pct}% booked`}><span style={{ width: `${pct}%` }} /></div>
                <div className="row-between">
                  <span className={soldOut ? 'badge danger' : s.seats_free < 15 ? 'badge warn' : 'badge'}>
                    {soldOut ? 'Sold out · join waitlist' : `${s.seats_free} ${s.seats_free === 1 ? 'seat' : 'seats'} left`}
                  </span>
                  <span className="muted small">from {rupees(s.regular_price_paise)}</span>
                </div>
              </div>
            </Link>
          )
        })}
      </div>
    </>
  )
}
