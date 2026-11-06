import { createContext, useContext, useEffect, useState } from 'react'
import { api, getToken, setToken } from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(() => !getToken())  // nothing to check without a saved token

  useEffect(() => {
    if (!getToken()) return
    api('/auth/me')
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setReady(true))
  }, [])

  const signIn = async (path, body) => {
    const res = await api(`/auth/${path}`, { method: 'POST', body })
    setToken(res.access_token)
    setUser(res.user)
    return res.user
  }

  const value = {
    user,
    ready,
    login: (email, password) => signIn('login', { email, password }),
    register: (name, email, password) => signIn('register', { name, email, password }),
    logout: () => { setToken(null); setUser(null) },
  }
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export const useAuth = () => useContext(AuthContext)
