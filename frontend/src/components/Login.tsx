import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Hexagon, Lock, User, ArrowRight } from 'lucide-react';
import api from '../api';

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
      } else {
        const { data } = await api.post('/auth/register', { username, email, password });
        localStorage.setItem('wire_token', data.access_token);
      }
      navigate('/dashboard');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'An error occurred during authentication.');
    }
  };

  return (
    <div className="auth-wrapper">
      <div className="glass-panel auth-form" style={{ padding: '40px' }}>
        <div style={{ textAlign: 'center', marginBottom: '20px' }}>
          <Hexagon size={48} color="var(--primary)" style={{ marginBottom: '16px' }} />
          <h2>Welcome to WIRE</h2>
          <p>{isLogin ? 'Sign in to the platform' : 'Create a new operator identity'}</p>
        </div>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <div style={{ position: 'relative' }}>
            <User size={18} style={{ position: 'absolute', left: '16px', top: '16px', color: 'var(--text-muted)' }} />
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
              <ArrowRight size={18} style={{ position: 'absolute', left: '16px', top: '16px', color: 'var(--text-muted)' }} />
              <input 
                type="email" 
                placeholder="Email Address" 
                value={email} onChange={e => setEmail(e.target.value)} 
                required 
                style={{ paddingLeft: '44px' }}
              />
            </div>
          )}

          <div style={{ position: 'relative' }}>
            <Lock size={18} style={{ position: 'absolute', left: '16px', top: '16px', color: 'var(--text-muted)' }} />
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
            {isLogin ? 'Authenticate' : 'Initialize Identity'}
          </button>
        </form>

        <div style={{ textAlign: 'center', marginTop: '20px' }}>
          <button 
            type="button" 
            onClick={() => setIsLogin(!isLogin)} 
            style={{ background: 'transparent', color: 'var(--text-muted)', padding: '0' }}
          >
            {isLogin ? "Don't have access? Request Identity" : "Already registered? Authenticate"}
          </button>
        </div>
      </div>
    </div>
  );
}
