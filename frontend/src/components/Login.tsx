import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Sparkles, Lock, User, Mail } from 'lucide-react';
import api, { apiErrorMessage } from '../api';

export default function Login() {
  const [isLogin, setIsLogin] = useState(true);
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      if (isLogin) {
        const params = new URLSearchParams();
        params.append('username', username);
        params.append('password', password);
        const { data } = await api.post('/auth/login', params);
        localStorage.setItem('wire_token', data.access_token);
        localStorage.setItem('wire_refresh_token', data.refresh_token);
      } else {
        const { data } = await api.post('/auth/register', { username, email, password });
        localStorage.setItem('wire_token', data.access_token);
        localStorage.setItem('wire_refresh_token', data.refresh_token);
      }
      navigate('/dashboard');
    } catch (err) {
      setError(apiErrorMessage(err, 'An error occurred during authentication.'));
    }
  };

  return (
    <div className="auth-wrapper">
      <div className="glass-panel auth-form" style={{ padding: '40px' }}>
        <div style={{ textAlign: 'center', marginBottom: '20px' }}>
          <Sparkles size={40} color="var(--primary)" style={{ marginBottom: '14px' }} />
          <h2>Welcome to WIRE</h2>
          <p>{isLogin ? 'Sign in to continue' : 'Create your account'}</p>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ position: 'relative' }}>
            <User size={18} style={{ position: 'absolute', left: '16px', top: '14px', color: 'var(--text-muted)' }} />
            <input
              type="text"
              placeholder="Username"
              value={username} onChange={e => setUsername(e.target.value)}
              required
              style={{ paddingLeft: '44px' }}
            />
          </div>

          {!isLogin && (
            <div style={{ position: 'relative' }}>
              <Mail size={18} style={{ position: 'absolute', left: '16px', top: '14px', color: 'var(--text-muted)' }} />
              <input
                type="email"
                placeholder="Email address"
                value={email} onChange={e => setEmail(e.target.value)}
                required
                style={{ paddingLeft: '44px' }}
              />
            </div>
          )}

          <div style={{ position: 'relative' }}>
            <Lock size={18} style={{ position: 'absolute', left: '16px', top: '14px', color: 'var(--text-muted)' }} />
            <input
              type="password"
              placeholder="Password"
              value={password} onChange={e => setPassword(e.target.value)}
              required
              style={{ paddingLeft: '44px' }}
            />
          </div>

          {error && <div style={{ color: 'var(--error)', fontSize: '0.9rem', textAlign: 'center' }}>{error}</div>}

          <button type="submit" className="btn-primary" style={{ marginTop: '8px' }}>
            {isLogin ? 'Sign in' : 'Create account'}
          </button>
        </form>

        <div style={{ textAlign: 'center', marginTop: '16px' }}>
          <button
            type="button"
            onClick={() => setIsLogin(!isLogin)}
            style={{ background: 'transparent', color: 'var(--text-muted)', padding: '0', fontSize: '0.88rem' }}
          >
            {isLogin ? "Don't have an account? Sign up" : "Already have an account? Sign in"}
          </button>
        </div>
      </div>
    </div>
  );
}
