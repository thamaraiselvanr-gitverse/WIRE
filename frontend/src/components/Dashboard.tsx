import { useState, useEffect } from 'react';
import { Target, Activity, FolderGit2 } from 'lucide-react';
import api from '../api';

export default function TelemetryConsole() {
  const [logs, setLogs] = useState<string[]>([]);
  
  useEffect(() => {
    // We append the token as a query parameter because EventSource doesn't support headers easily natively
    const token = localStorage.getItem('wire_token');
    if (!token) return;
    
    // In a real app we might proxy this or use fetch-event-source, but native works if the backend tolerates it
    // For now we'll use a standard EventSource mapping to our API.
    const eventSource = new EventSource(`http://localhost:8000/api/projects/telemetry`);
    
    eventSource.onmessage = (event) => {
      setLogs((prev) => [...prev.slice(-49), event.data]);
    };
    
    return () => eventSource.close();
  }, []);

  return (
    <div className="glass-panel" style={{ height: '400px', display: 'flex', flexDirection: 'column' }}>
      <div style={{ paddingBottom: '16px', borderBottom: '1px solid var(--panel-border)', marginBottom: '16px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <Activity size={18} color="var(--primary)" />
        <h3 style={{ margin: 0, fontSize: '1.1rem' }}>Platform Telemetry</h3>
      </div>
      
      <div style={{ flex: 1, overflowY: 'auto', fontFamily: 'monospace', fontSize: '0.85rem', color: '#a0aabf' }}>
        {logs.length === 0 ? (
          <div style={{ display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
            Awaiting systemic operations...
          </div>
        ) : (
          logs.map((log, idx) => (
            <div key={idx} style={{ marginBottom: '4px' }}>
              <span style={{ color: 'var(--success)' }}>{'>'}</span> {log}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export function CommandCenter() {
  const [url, setUrl] = useState('');
  const [projects, setProjects] = useState<any[]>([]);
  const [selectedProject, setSelectedProject] = useState<any | null>(null);
  const [activeTab, setActiveTab] = useState<'visuals' | 'code' | 'prompts'>('visuals');
  const [codeType, setCodeType] = useState<'react' | 'vue' | 'html'>('react');
  const [fileContent, setFileContent] = useState<string>('');
  const [fileLoading, setFileLoading] = useState(false);
  const [prompts, setPrompts] = useState<string[]>([]);

  useEffect(() => {
    fetchProjects();
  }, []);

  useEffect(() => {
    if (selectedProject) {
      if (activeTab === 'code') {
        fetchCode();
      } else if (activeTab === 'prompts') {
        fetchPrompts();
      }
    } else {
      setFileContent('');
      setPrompts([]);
    }
  }, [selectedProject, activeTab, codeType]);

  const fetchProjects = async () => {
    try {
      const { data } = await api.get('/projects');
      setProjects(data);
    } catch (e) { console.error(e); }
  };

  const fetchCode = async () => {
    if (!selectedProject) return;
    setFileLoading(true);
    try {
      const filename = codeType === 'react' ? 'output_react.jsx' : codeType === 'vue' ? 'output_vue.vue' : 'index.html';
      const { data } = await api.get(`/projects/${selectedProject.id}/files/${filename}`);
      // If data is an object, stringify it, otherwise it's text content
      setFileContent(typeof data === 'object' ? JSON.stringify(data, null, 2) : data);
    } catch (e) {
      setFileContent('Error loading source code file. Make sure it is compiled successfully.');
      console.error(e);
    } finally {
      setFileLoading(false);
    }
  };

  const fetchPrompts = async () => {
    if (!selectedProject) return;
    setFileLoading(true);
    try {
      const { data } = await api.get(`/projects/${selectedProject.id}/files/ai_design_prompts.json`);
      setPrompts(Array.isArray(data) ? data : []);
    } catch (e) {
      setPrompts(['Error loading AI prompts.']);
      console.error(e);
    } finally {
      setFileLoading(false);
    }
  };

  const handleReconstruct = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!url) return;
    try {
      await api.post('/projects', { url });
      setUrl('');
      fetchProjects(); // refresh list
    } catch (e) {
      console.error(e);
    }
  };

  const token = localStorage.getItem('wire_token');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      <div className="glass-panel">
        <h2 style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <Target size={24} color="var(--primary)" /> Initialization Vector
        </h2>
        <p style={{ marginBottom: '20px' }}>Provide a target domain for semantic reconstruction.</p>
        
        <form onSubmit={handleReconstruct} style={{ display: 'flex', gap: '16px' }}>
          <input 
            type="url" 
            placeholder="https://example.com" 
            value={url} 
            onChange={e => setUrl(e.target.value)}
            style={{ flex: 1 }}
            required
          />
          <button type="submit" className="btn-primary">Initiate Extraction</button>
        </form>
      </div>

      <div className="glass-panel">
        <h2 style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '20px' }}>
          <FolderGit2 size={24} color="var(--primary)" /> Extracted Templates
        </h2>
        
        {projects.length === 0 ? (
          <p>No extractions exist in the current workspace.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {projects.map((p, i) => (
              <div key={i} style={{ padding: '16px', background: 'rgba(0,0,0,0.3)', borderRadius: '8px', border: '1px solid var(--panel-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <div style={{ fontWeight: 600, color: '#fff' }}>{p.url}</div>
                  <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)' }}>Status: <span style={{ color: p.status === 'completed' ? 'var(--success)' : 'var(--primary)' }}>{p.status}</span></div>
                </div>
                {p.status === 'completed' && (
                  <button 
                    onClick={() => {
                      setSelectedProject(p);
                      setActiveTab('visuals');
                    }}
                    className="btn-primary" 
                    style={{ padding: '8px 16px', fontSize: '0.85rem' }}
                  >
                    View Assets
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Asset Viewer Modal */}
      {selectedProject && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: 'rgba(0,0,0,0.85)',
          backdropFilter: 'blur(8px)',
          WebkitBackdropFilter: 'blur(8px)',
          zIndex: 1000,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '24px'
        }}>
          <div style={{
            width: '100%',
            maxWidth: '1100px',
            height: '90%',
            background: '#0d0e12',
            border: '1px solid var(--panel-border)',
            borderRadius: '16px',
            padding: '24px',
            display: 'flex',
            flexDirection: 'column',
            gap: '20px',
            boxShadow: '0 20px 50px rgba(0,0,0,0.6)'
          }}>
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--panel-border)', paddingBottom: '16px' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '1.25rem' }}>Assets Viewer</h3>
                <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-muted)' }}>{selectedProject.url}</p>
              </div>
              <button 
                onClick={() => setSelectedProject(null)}
                style={{
                  background: 'rgba(255,255,255,0.05)',
                  border: '1px solid var(--panel-border)',
                  color: '#fff',
                  padding: '8px 16px',
                  borderRadius: '6px',
                  fontSize: '0.85rem'
                }}
              >
                Close Panel
              </button>
            </div>

            {/* Tab Controls */}
            <div style={{ display: 'flex', gap: '12px' }}>
              <button 
                onClick={() => setActiveTab('visuals')}
                style={{
                  background: activeTab === 'visuals' ? 'var(--primary)' : 'transparent',
                  color: activeTab === 'visuals' ? '#000' : 'var(--text-muted)',
                  border: activeTab === 'visuals' ? 'none' : '1px solid var(--panel-border)',
                  padding: '8px 16px',
                  borderRadius: '6px',
                  fontSize: '0.9rem'
                }}
              >
                Visual Captures
              </button>
              <button 
                onClick={() => setActiveTab('code')}
                style={{
                  background: activeTab === 'code' ? 'var(--primary)' : 'transparent',
                  color: activeTab === 'code' ? '#000' : 'var(--text-muted)',
                  border: activeTab === 'code' ? 'none' : '1px solid var(--panel-border)',
                  padding: '8px 16px',
                  borderRadius: '6px',
                  fontSize: '0.9rem'
                }}
              >
                Compiled Code
              </button>
              <button 
                onClick={() => setActiveTab('prompts')}
                style={{
                  background: activeTab === 'prompts' ? 'var(--primary)' : 'transparent',
                  color: activeTab === 'prompts' ? '#000' : 'var(--text-muted)',
                  border: activeTab === 'prompts' ? 'none' : '1px solid var(--panel-border)',
                  padding: '8px 16px',
                  borderRadius: '6px',
                  fontSize: '0.9rem'
                }}
              >
                AI Design Prompts
              </button>
            </div>

            {/* Content Body */}
            <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
              {activeTab === 'visuals' && (
                <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '32px', padding: '8px' }}>
                  <div>
                    <h4 style={{ fontSize: '1rem', marginBottom: '12px' }}>Desktop Capture (1920px)</h4>
                    <img 
                      src={`http://localhost:8000/api/projects/${selectedProject.id}/files/assets/capture_desktop.png?token=${token}`} 
                      alt="Desktop View" 
                      style={{ width: '100%', borderRadius: '8px', border: '1px solid var(--panel-border)', background: '#000' }}
                    />
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
                    <div>
                      <h4 style={{ fontSize: '1rem', marginBottom: '12px' }}>Tablet Capture (768px)</h4>
                      <img 
                        src={`http://localhost:8000/api/projects/${selectedProject.id}/files/assets/capture_tablet.png?token=${token}`} 
                        alt="Tablet View" 
                        style={{ width: '100%', borderRadius: '8px', border: '1px solid var(--panel-border)', background: '#000' }}
                      />
                    </div>
                    <div>
                      <h4 style={{ fontSize: '1rem', marginBottom: '12px' }}>Mobile Capture (375px)</h4>
                      <img 
                        src={`http://localhost:8000/api/projects/${selectedProject.id}/files/assets/capture_mobile.png?token=${token}`} 
                        alt="Mobile View" 
                        style={{ width: '100%', borderRadius: '8px', border: '1px solid var(--panel-border)', background: '#000' }}
                      />
                    </div>
                  </div>
                </div>
              )}

              {activeTab === 'code' && (
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '12px', overflow: 'hidden' }}>
                  {/* Code Type Selectors */}
                  <div style={{ display: 'flex', gap: '8px' }}>
                    <button 
                      onClick={() => setCodeType('react')}
                      style={{
                        padding: '6px 12px',
                        fontSize: '0.8rem',
                        borderRadius: '4px',
                        background: codeType === 'react' ? 'rgba(69, 243, 255, 0.1)' : 'transparent',
                        color: codeType === 'react' ? 'var(--primary)' : 'var(--text-muted)',
                        border: '1px solid ' + (codeType === 'react' ? 'var(--primary)' : 'var(--panel-border)')
                      }}
                    >
                      React Component (.jsx)
                    </button>
                    <button 
                      onClick={() => setCodeType('vue')}
                      style={{
                        padding: '6px 12px',
                        fontSize: '0.8rem',
                        borderRadius: '4px',
                        background: codeType === 'vue' ? 'rgba(69, 243, 255, 0.1)' : 'transparent',
                        color: codeType === 'vue' ? 'var(--primary)' : 'var(--text-muted)',
                        border: '1px solid ' + (codeType === 'vue' ? 'var(--primary)' : 'var(--panel-border)')
                      }}
                    >
                      Vue Component (.vue)
                    </button>
                    <button 
                      onClick={() => setCodeType('html')}
                      style={{
                        padding: '6px 12px',
                        fontSize: '0.8rem',
                        borderRadius: '4px',
                        background: codeType === 'html' ? 'rgba(69, 243, 255, 0.1)' : 'transparent',
                        color: codeType === 'html' ? 'var(--primary)' : 'var(--text-muted)',
                        border: '1px solid ' + (codeType === 'html' ? 'var(--primary)' : 'var(--panel-border)')
                      }}
                    >
                      Raw HTML (.html)
                    </button>
                  </div>

                  {/* Code Viewport */}
                  <div style={{ flex: 1, overflow: 'auto', background: '#050608', border: '1px solid var(--panel-border)', borderRadius: '8px', padding: '16px', position: 'relative' }}>
                    {fileLoading ? (
                      <div style={{ color: 'var(--text-muted)', display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center' }}>
                        Loading source files...
                      </div>
                    ) : (
                      <pre style={{ margin: 0, fontFamily: 'monospace', fontSize: '0.85rem', color: '#a0aabf', whiteSpace: 'pre-wrap' }}>
                        <code>{fileContent}</code>
                      </pre>
                    )}
                  </div>
                </div>
              )}

              {activeTab === 'prompts' && (
                <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px', padding: '8px' }}>
                  {fileLoading ? (
                    <div style={{ color: 'var(--text-muted)', display: 'flex', height: '100%', alignItems: 'center', justifyContent: 'center' }}>
                      Loading Prompts...
                    </div>
                  ) : prompts.length === 0 ? (
                    <p style={{ color: 'var(--text-muted)' }}>No design prompts generated for this template.</p>
                  ) : (
                    prompts.map((p, idx) => (
                      <div key={idx} style={{ padding: '16px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--panel-border)', borderRadius: '8px' }}>
                        <div style={{ fontWeight: 600, color: 'var(--primary)', marginBottom: '8px', fontSize: '0.9rem' }}>Prompt Block #{idx + 1}</div>
                        <div style={{ fontSize: '0.9rem', color: '#dfdfe6', whiteSpace: 'pre-wrap', fontFamily: 'Inter, sans-serif' }}>{p}</div>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
