import { useEffect, useState } from 'react'

// mm:ss until `until`; calls onExpire once when it reaches zero.
export default function Countdown({ until, onExpire }) {
  const left = () => Math.max(0, Math.round((new Date(until) - Date.now()) / 1000))
  const [secs, setSecs] = useState(left)

  useEffect(() => {
    const t = setInterval(() => {
      const s = left()
      setSecs(s)
      if (s === 0) { clearInterval(t); onExpire?.() }
    }, 500)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [until])

  const mm = String(Math.floor(secs / 60)).padStart(2, '0')
  const ss = String(secs % 60).padStart(2, '0')
  return <span className={`countdown ${secs < 60 ? 'urgent' : ''}`}>{mm}:{ss}</span>
}
