import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import FreeCloudApp from './FreeCloudApp'
import './style.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {import.meta.env.VITE_FREE_CLOUD === 'true' ? <FreeCloudApp /> : <App />}
  </React.StrictMode>,
)
