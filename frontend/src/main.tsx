import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './App';
import { ApiStatusProvider } from './contexts/ApiStatusContext';
import { SelectedInstrumentProvider } from './contexts/SelectedInstrumentContext';
import './styles/index.css';

const container = document.getElementById('root');
if (!container) {
  throw new Error('Root element #root was not found in index.html');
}

createRoot(container).render(
  <StrictMode>
    <BrowserRouter>
      <ApiStatusProvider>
        <SelectedInstrumentProvider>
          <App />
        </SelectedInstrumentProvider>
      </ApiStatusProvider>
    </BrowserRouter>
  </StrictMode>,
);
