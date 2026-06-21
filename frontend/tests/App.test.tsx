import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import App from '../src/App';

describe('App Integration', () => {
  it('renders the main heading', () => {
    // Structural rendering test
    render(<App />);
    const headerElement = screen.getByText(/WIRE/i);
    expect(headerElement).toBeDefined();
  });
});
