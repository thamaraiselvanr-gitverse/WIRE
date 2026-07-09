/**
 * Dashboard flow tests: project list, reconstruction submit, asset viewer
 * (scoped file token, tab semantics, Escape-to-close), content editor labels,
 * and telemetry console. These also pin the accessibility contract
 * (roles/labels/keyboard) so regressions fail loudly.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// Mock the api module: route GET/POST by URL. Individual tests override
// handlers through the shared `routes` table.
const routes: {
  get: Record<string, unknown>;
  post: Array<{ url: string; body: unknown }>;
} = { get: {}, post: [] };

vi.mock('../src/api', () => ({
  default: {
    get: vi.fn(async (url: string) => {
      for (const [pattern, data] of Object.entries(routes.get)) {
        if (url.includes(pattern)) return { data };
      }
      throw Object.assign(new Error(`404 ${url}`), { response: { status: 404 } });
    }),
    post: vi.fn(async (url: string, body: unknown) => {
      routes.post.push({ url, body });
      return { data: { message: 'ok', project_id: 99 } };
    }),
  },
  API_BASE: 'http://test/api',
  apiErrorMessage: (_e: unknown, fallback = 'error') => fallback,
}));

import TelemetryConsole, { CommandCenter } from '../src/components/Dashboard';

const PROJECTS = [
  { id: 1, url: 'https://done.example', status: 'completed', fidelity_score: 91 },
  { id: 2, url: 'https://pending.example', status: 'pending' },
];

beforeEach(() => {
  routes.get = {
    '/file-token': { file_token: 'scoped-ft', expires_in: 900 },
    website_form_schema: {
      fields: [
        { field_id: 'headline', field_type: 'text', label: 'Hero Heading', required: true },
      ],
    },
    '/projects': PROJECTS,
  };
  routes.post = [];
  localStorage.clear();
});

describe('CommandCenter — project list & reconstruct', () => {
  it('lists projects and only completed ones offer View Assets', async () => {
    render(<CommandCenter />);
    expect(await screen.findByText('https://done.example')).toBeInTheDocument();
    expect(screen.getByText('https://pending.example')).toBeInTheDocument();
    expect(screen.getAllByRole('button', { name: 'View Assets' })).toHaveLength(1);
  });

  it('submits a reconstruction via the labeled URL input', async () => {
    const user = userEvent.setup();
    render(<CommandCenter />);
    // Accessible name pinned: placeholder alone is not a label.
    const input = await screen.findByLabelText('Website URL to reconstruct');
    await user.type(input, 'https://new.example');
    await user.click(screen.getByRole('button', { name: 'Reconstruct' }));
    await waitFor(() =>
      expect(routes.post.some((p) => p.url === '/projects')).toBe(true),
    );
    const call = routes.post.find((p) => p.url === '/projects');
    expect(call?.body).toEqual({ url: 'https://new.example' });
  });
});

describe('CommandCenter — asset viewer dialog', () => {
  async function openViewer() {
    const user = userEvent.setup();
    render(<CommandCenter />);
    await user.click(await screen.findByRole('button', { name: 'View Assets' }));
    return user;
  }

  it('opens an accessible dialog and fetches a scoped file token', async () => {
    await openViewer();
    const dialog = await screen.findByRole('dialog', {
      name: /assets viewer for https:\/\/done\.example/i,
    });
    expect(dialog).toBeInTheDocument();
    // The previews must embed the short-lived scoped token, never the session JWT.
    const img = (await screen.findByAltText('Desktop View')) as HTMLImageElement;
    await waitFor(() => expect(img.src).toContain('token=scoped-ft'));
  });

  it('exposes tab semantics with selection state', async () => {
    const user = await openViewer();
    const tablist = await screen.findByRole('tablist', { name: 'Asset views' });
    expect(tablist).toBeInTheDocument();
    const tabs = screen.getAllByRole('tab');
    expect(tabs).toHaveLength(5);
    expect(screen.getByRole('tab', { name: 'Visual Captures', selected: true })).toBeInTheDocument();
    await user.click(screen.getByRole('tab', { name: 'Live Preview' }));
    expect(screen.getByRole('tab', { name: 'Live Preview', selected: true })).toBeInTheDocument();
  });

  it('closes on Escape (keyboard parity with the Close button)', async () => {
    const user = await openViewer();
    await screen.findByRole('dialog');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('content editor fields are reachable by their labels', async () => {
    const user = await openViewer();
    await user.click(await screen.findByRole('tab', { name: 'Content Editor' }));
    // htmlFor/id association pinned: getByLabelText fails without it.
    const field = await screen.findByLabelText(/Hero Heading/);
    expect(field.tagName).toBe('INPUT');
    await user.type(field, 'My new headline');
    expect((field as HTMLInputElement).value).toBe('My new headline');
  });
});

describe('TelemetryConsole', () => {
  it('renders an aria-live log region without a session', () => {
    // No token in localStorage -> no EventSource; the region still exists.
    render(<TelemetryConsole />);
    const log = screen.getByRole('log', { name: 'Pipeline telemetry' });
    expect(log).toBeInTheDocument();
    expect(screen.getByText(/awaiting systemic operations/i)).toBeInTheDocument();
  });
});
