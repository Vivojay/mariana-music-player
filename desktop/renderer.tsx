import React from 'react'
import ReactDOM from 'react-dom/client'
import '@fontsource-variable/cascadia-code/index.css'
import App from './App'
import MiniPlayerApp from './MiniPlayerApp'
import VideoWindowApp from './VideoWindowApp'
import './styles.css'

const surface = new URLSearchParams(window.location.search).get('surface')
document.title = surface === 'mini' ? 'Mariana Mini-player' : surface === 'video' ? 'Mariana Video' : 'Mariana'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>{surface === 'mini' ? <MiniPlayerApp /> : surface === 'video' ? <VideoWindowApp /> : <App />}</React.StrictMode>,
)
