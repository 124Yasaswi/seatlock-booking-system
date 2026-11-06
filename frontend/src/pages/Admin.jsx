import { useEffect, useState } from 'react'
import { api, rupees, showTime } from '../api'

function BarChart({ data, label }) {
  // Simple SVG bar chart, 24 hours on the x axis
  const max = Math.max(1, ...data.map((d) => d.value))
  const W = 480, H = 160, bw = W / data.length
  return (
    <svg viewBox={`0 0 ${W} ${H + 22}`} className="chart" role="img" aria-label={label}>
      {data.map((d, i) => {
        const h = (d.value / max) * H
        return (
          <g key={d.key}>
            <rect x={i * bw + 2} y={H - h} width={bw - 4} height={h} rx="2" className="bar"><title>{`${d.key}: ${d.value}`}</title></rect>
            {i % 3 === 0 && <text x={i * bw + bw / 2} y={H + 16} className="axis" textAnchor="middle">{d.key}</text>}
          </g>
        )
      })}
    </svg>
  )
}

function Heatmap({ seats }) {
  const max = Math.max(1, ...seats.map((s) => s.times_booked))
  const rows = []
  for (const s of seats) (rows[s.row_index] ??= { label: s.row_label, seats: [] }).seats.push(s)
  return (
    <div className="heatmap">
      <div className="screen small">SCREEN</div>
      {rows.filter(Boolean).map((r) => (
        <div key={r.label} className="heat-row">
          <span className="row-label">{r.label}</span>
          {r.seats.map((s) => (
            <span key={s.seat_id} className="heat" title={`${s.row_label}${s.seat_number}: booked ${s.times_booked}×`}
              style={{ '--heat': s.times_booked / max }} />
          ))}
        </div>
      ))}
      <div className="heat-scale"><span>rarely booked</span><i /><span>most booked</span></div>
    </div>
  )
}

export default function Admin() {
  const [d, setD] = useState(null)
  const [venues, setVenues] = useState([])
  const [venue, setVenue] = useState(null)
  const [heat, setHeat] = useState([])
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api('/admin/dashboard'), api('/admin/venues')])
      .then(([dash, v]) => { setD(dash); setVenues(v); setVenue(v[0]?.id ?? null) })
      .catch((e) => setError(e.message))
  }, [])

  useEffect(() => {
    if (venue) api(`/admin/venues/${venue}/heatmap`).then(setHeat).catch((e) => setError(e.message))
  }, [venue])

  if (error) return <p className="error">{error}</p>
  if (!d) return <p className="muted center">Loading dashboard…</p>

  const hours = Array.from({ length: 24 }, (_, h) => ({ key: `${h}h`, value: d.by_hour.find((x) => x.hour === h)?.bookings ?? 0 }))

  return (
    <div className="stack">
      <h1>Dashboard</h1>
      <div className="stats">
        <div className="card stat"><span className="muted">Revenue</span><strong>{rupees(d.summary.revenue_paise)}</strong></div>
        <div className="card stat"><span className="muted">Bookings</span><strong>{d.summary.bookings}</strong></div>
        <div className="card stat"><span className="muted">Cancellations</span><strong>{d.summary.cancellations}</strong></div>
        <div className="card stat"><span className="muted">Cancel rate</span><strong>{d.summary.cancel_rate_pct ?? 0}%</strong></div>
      </div>

      <div className="two-col">
        <section className="card">
          <h2>When do people book?</h2>
          <p className="muted small">Confirmed bookings by hour of the day (IST)</p>
          <BarChart data={hours} label="Bookings by hour" />
        </section>
        <section className="card">
          <div className="row-between">
            <h2>Seat heatmap</h2>
            <select value={venue ?? ''} onChange={(e) => setVenue(Number(e.target.value))} aria-label="Venue">
              {venues.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
            </select>
          </div>
          <p className="muted small">Which seats sell most across all shows</p>
          <Heatmap seats={heat} />
        </section>
      </div>

      <section className="card">
        <h2>Shows</h2>
        <div className="table-wrap">
          <table>
            <thead><tr><th>#</th><th>Show</th><th>Starts</th><th>Occupancy</th><th className="num">Revenue</th></tr></thead>
            <tbody>
              {d.shows.map((s) => (
                <tr key={s.id}>
                  <td>{s.revenue_rank}</td>
                  <td>{s.title}</td>
                  <td className="nowrap">{showTime(s.starts_at)}</td>
                  <td><div className="fill"><span style={{ width: `${s.occupancy_pct}%` }} /></div><small className="muted">{s.seats_sold}/{s.seats_total} · {s.occupancy_pct}%</small></td>
                  <td className="num">{rupees(s.revenue_paise)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="muted small"># = revenue rank, computed in SQL with RANK() OVER (ORDER BY revenue DESC)</p>
      </section>
    </div>
  )
}
