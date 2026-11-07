import React from 'react'
import ReactDOM from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import './index.css'
import App from './App'
import { I18nProvider } from './i18n'
import { ThemeProvider } from './theme/ThemeProvider'
import { ToastProvider } from './components/ui/overlay'
import { AppProvider } from './store/AppContext'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <HashRouter>
      <ThemeProvider defaultTheme="system">
        <I18nProvider defaultLocale="en">
          <ToastProvider>
            <AppProvider>
              <App />
            </AppProvider>
          </ToastProvider>
        </I18nProvider>
      </ThemeProvider>
    </HashRouter>
  </React.StrictMode>,
)
