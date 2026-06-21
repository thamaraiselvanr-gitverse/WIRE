import { BrowserRouter as Router, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { Hexagon, LogOut } from 'lucide-react';
import Login from './components/Login';
import TelemetryConsole, { CommandCenter } from './components/Dashboard';

function ProtectedRoute({ children }: { children: JSX.Element }) {
  const token = localStorage.getItem('wire_token');
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function MainLayout({ children }: { children: JSX.Element }) {
  const navigate = useNavigate();
  const handleLogout = () => {
    localStorage.removeItem('wire_token');
    navigate('/login');
  };

  return (
    <>
      <nav className="navbar">
        <a href="/" className="nav-logo">
          <Hexagon /> WIRE PLATFORM
        </a>
        <div className="nav-links">
          <a href="/dashboard" className="active">Command Center</a>
          <a href="/settings">Settings</a>
          <button 
            onClick={handleLogout}
            style={{ background: 'transparent', padding: '0', display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--error)' }}
          >
            <LogOut size={16} /> Logout
          </button>
        </div>
      </nav>
      <main className="container">
        {children}
      </main>
    </>
  );
}

function DashboardView() {
  return (
    <MainLayout>
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '32px' }}>
        <CommandCenter />
        <TelemetryConsole />
      </div>
    </MainLayout>
  );
}

function App() {
  return (
    <Router>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/dashboard" element={
          <ProtectedRoute>
            <DashboardView />
          </ProtectedRoute>
        } />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </Router>
  );
}

export default App;
