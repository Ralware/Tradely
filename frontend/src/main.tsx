import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import { SelectedInstrumentProvider } from './contexts/SelectedInstrumentContext';
import { snapshotHydrator } from './services/snapshotHydrator';
import './styles/index.css';

// Hydration runs outside route/component lifecycles and does not block app startup.
void snapshotHydrator.start();

const container = document.getElementById('root');
if (!container) {
  throw new Error('Root element #root was not found in index.html');
}

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <SelectedInstrumentProvider>
        <App />
      </SelectedInstrumentProvider>
    </BrowserRouter>
  </StrictMode>,
);
