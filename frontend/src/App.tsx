import type { ReactElement } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { Sparkles, LayoutGrid, Settings, LogOut } from 'lucide-react';
import Login from './components/Login';
import TelemetryConsole, { CommandCenter } from './components/Dashboard';

function ProtectedRoute({ children }: { children: ReactElement }) {
  const token = localStorage.getItem('wire_token');
  if (!token) {
    return <Navigate to="/login" replace />;
  }
  return children;
}

function MainLayout({ children }: { children: ReactElement }) {
  const navigate = useNavigate();
  const handleLogout = () => {
    localStorage.removeItem('wire_token');
    navigate('/login');
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <Sparkles size={20} color="var(--primary)" />
          <span>
            WIRE
            <small>Semantic Web Reconstructor</small>
          </span>
        </div>

        <nav className="sidebar-nav">
          <a href="/dashboard" className="sidebar-item active">
            <LayoutGrid size={17} /> Workspace
          </a>
          <a href="/settings" className="sidebar-item">
            <Settings size={17} /> Settings
          </a>
        </nav>

        <div className="sidebar-footer">
          <button className="sidebar-item" onClick={handleLogout}>
            <LogOut size={17} /> Sign out
          </button>
        </div>
      </aside>

      <main className="workspace">{children}</main>
    </div>
  );
}

function DashboardView() {
  return (
    <MainLayout>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0, 1.35fr) minmax(0, 0.65fr)',
          gap: '28px',
          alignItems: 'start',
        }}
      >
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
