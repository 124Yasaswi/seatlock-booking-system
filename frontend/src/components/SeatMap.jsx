// The seat grid. Pure HTML buttons laid out with CSS grid, one row per seat row.
// `mine` = seats in my current hold, `selected` = seats I am picking right now.

export default function SeatMap({ seats, selected, mine, onToggle, disabled }) {
  const rows = []
  for (const s of seats) {
    const r = rows[s.row_index] ?? (rows[s.row_index] = { label: s.row_label, seats: [] })
    r.seats.push(s)
  }
  const perRow = Math.max(...rows.filter(Boolean).map((r) => r.seats.length))

  return (
    <div className="seatmap" role="grid" aria-label="Seat map">
      <div className="screen">SCREEN THIS WAY</div>
      {rows.filter(Boolean).map((row) => (
        <div key={row.label} className="seat-row" style={{ '--cols': perRow }} role="row">
          <span className="row-label">{row.label}</span>
          {row.seats.map((s) => {
            const state = mine.has(s.id) ? 'mine' : selected.has(s.id) ? 'selected' : s.status
            const clickable = !disabled && (state === 'available' || state === 'selected')
            return (
              <button
                key={s.id}
                className={`seat ${state} ${s.category}`}
                disabled={!clickable}
                onClick={() => onToggle(s.id)}
                aria-label={`Seat ${s.row_label}${s.seat_number}, ${s.category}, ${state}`}
                aria-pressed={state === 'selected'}
              >
                {s.seat_number}
              </button>
            )
          })}
          <span className="row-label">{row.label}</span>
        </div>
      ))}
    </div>
  )
}
