import { Link, Navigate, NavLink, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth.jsx'
import Admin from './pages/Admin.jsx'
import Login from './pages/Login.jsx'
import MyBookings from './pages/MyBookings.jsx'
import SeatPage from './pages/SeatPage.jsx'
import Shows from './pages/Shows.jsx'

function RequireUser({ children, admin = false }) {
  const { user, ready } = useAuth()
  if (!ready) return <p className="muted center">Loading…</p>
  if (!user) return <Navigate to="/login" replace />
  if (admin && user.role !== 'admin') return <Navigate to="/" replace />
  return children
}

export default function App() {
  const { user, logout } = useAuth()
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand"><span className="logo" aria-hidden>▣</span> SeatLock</Link>
        <nav>
          <NavLink to="/" end>Shows</NavLink>
          {user && <NavLink to="/me">My bookings</NavLink>}
          {user?.role === 'admin' && <NavLink to="/admin">Dashboard</NavLink>}
          {user
            ? <button className="link" onClick={logout}>Sign out</button>
            : <NavLink to="/login">Sign in</NavLink>}
        </nav>
      </header>
      <main className="container">
        <Routes>
          <Route path="/" element={<Shows />} />
          <Route path="/shows/:id" element={<SeatPage />} />
          <Route path="/login" element={<Login />} />
          <Route path="/me" element={<RequireUser><MyBookings /></RequireUser>} />
          <Route path="/admin" element={<RequireUser admin><Admin /></RequireUser>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
      <footer className="footer muted">SeatLock · FastAPI + PostgreSQL + React · a portfolio project</footer>
    </>
  )
}
