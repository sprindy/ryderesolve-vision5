// Pages work with backend routes or a separate local static server on 5173.
// Change apiBase if the API runs on another origin/port.
window.RYDE_CONFIG = {
  apiBase: window.location.port === '5173' ? 'http://127.0.0.1:8000' : ''
};
if (window.location.protocol === 'file:') {
  window.addEventListener('DOMContentLoaded', () => {
    const notice = document.getElementById('notice');
    if (notice) {
      notice.hidden = false;
      notice.className = 'notice error';
      notice.textContent = 'Open this app through http://127.0.0.1:8000/rider, /driver or /admin after starting the backend. File preview does not run the API.';
    }
  });
}
