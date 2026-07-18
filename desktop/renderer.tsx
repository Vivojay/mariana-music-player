import React from 'react'
import ReactDOM from 'react-dom/client'
import '@fontsource-variable/cascadia-code/index.css'
import App from './App'
import MiniPlayerApp from './MiniPlayerApp'
import './styles.css'

const miniPlayer = new URLSearchParams(window.location.search).get('surface') === 'mini'
document.title = miniPlayer ? 'Mariana Mini-player' : 'Mariana'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>{miniPlayer ? <MiniPlayerApp /> : <App />}</React.StrictMode>,
)
