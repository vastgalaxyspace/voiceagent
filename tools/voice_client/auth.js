'use strict';
(() => {
  const element = id => document.getElementById(id);
  let token = null;

  function changed() {
    element('auth-form').hidden = Boolean(token);
    element('account').hidden = !token;
    window.dispatchEvent(new Event('voiceauthchange'));
  }

  async function api(path, options = {}) {
    const headers = {'Content-Type': 'application/json', ...(options.headers || {})};
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch(path, {...options, headers});
    if (response.status === 204) return null;
    const body = await response.json();
    if (!response.ok) {
      if (response.status === 401 && token) { token = null; changed(); }
      throw new Error(body.error || 'Request failed');
    }
    return body;
  }

  window.voiceAuth = {api, getToken: () => token};
  element('auth-form').addEventListener('submit', async event => {
    event.preventDefault();
    const buttons = [...element('auth-form').querySelectorAll('button')];
    buttons.forEach(button => { button.disabled = true; });
    const credentials = {email: element('email').value, password: element('password').value};
    try {
      if (event.submitter?.id === 'register') {
        await api('/api/v1/auth/register', {method: 'POST', body: JSON.stringify(credentials)});
      }
      const result = await api('/api/v1/auth/login', {method: 'POST', body: JSON.stringify(credentials)});
      token = result.access_token;
      const preferences = await api('/api/v1/users/me/preferences');
      element('language').value = preferences.language;
      element('detail').value = preferences.response_detail;
      element('goal').value = preferences.goal;
      element('account-email').textContent = credentials.email;
      element('auth-status').textContent = '';
      changed();
    } catch (error) {
      token = null;
      element('auth-status').textContent = error.message;
    } finally {
      element('password').value = '';
      buttons.forEach(button => { button.disabled = false; });
    }
  });

  element('logout').onclick = async () => {
    try { await api('/api/v1/auth/logout', {method: 'POST'}); }
    catch (error) { element('auth-status').textContent = error.message; }
    finally { token = null; changed(); }
  };
})();
