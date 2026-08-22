(() => {
  const loginPanel = document.querySelector('#loginPanel');
  const loginForm = document.querySelector('#loginForm');
  const password = document.querySelector('#password');
  const loginStatus = document.querySelector('#loginStatus');
  const dashboard = document.querySelector('#dashboard');
  const pairCollector = document.querySelector('#pairCollector');
  const pairPublisher = document.querySelector('#pairPublisher');
  const connectionStatus = document.querySelector('#connectionStatus');
  const logout = document.querySelector('#logout');
  const diagnostics = document.querySelector('#diagnostics');

  let csrfToken = '';

  const setStatus = (element, text, tone = '') => {
    element.textContent = text;
    element.className = `status ${tone}`.trim();
  };

  const setBusy = (busy) => {
    pairCollector.disabled = busy;
    pairPublisher.disabled = busy;
    logout.disabled = busy;
  };

  const enterDashboard = () => {
    loginPanel.hidden = true;
    loginPanel.style.display = 'none';
    dashboard.hidden = false;
    dashboard.style.display = 'block';
  };

  const loadDiagnostics = async () => {
    if (!diagnostics) return;
    try {
      const rows = await api('/api/admin/coupang/diagnostics?limit=40');
      diagnostics.textContent = rows.length ? rows.map((row) => {
        const time = row.updated_at || row.started_at || '';
        const detail = row.error_message || JSON.stringify(row.context || {});
        return `[${time}] ${row.status} · ${row.step || '-'} · ${row.product_name || '-'}${detail ? `\n  ${detail}` : ''}`;
      }).join('\n\n') : '아직 쿠팡 자동 실행 기록이 없습니다.';
    } catch (error) {
      diagnostics.textContent = `진단 로그를 불러오지 못했습니다: ${error.message || error}`;
    }
  };

  const leaveDashboard = (message = '로그인 후 쿠팡 확장 연결 상태를 확인할 수 있습니다.') => {
    csrfToken = '';
    dashboard.hidden = true;
    dashboard.style.display = 'none';
    loginPanel.hidden = false;
    loginPanel.style.display = 'grid';
    setStatus(loginStatus, message);
  };

  const api = async (path, options = {}) => {
    const headers = { ...(options.headers || {}) };
    if (options.method && options.method !== 'GET') {
      headers['Content-Type'] = 'application/json';
      headers['X-CSRF-Token'] = csrfToken;
    }
    const response = await fetch(path, {
      ...options,
      headers,
      credentials: 'same-origin',
      cache: 'no-store',
    });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401) {
      leaveDashboard('세션이 만료됐습니다. 다시 로그인해 주세요.');
      throw new Error('세션이 만료됐습니다.');
    }
    if (!response.ok || !payload.ok) throw new Error(payload.error || '요청을 처리하지 못했습니다.');
    return payload.result;
  };

  const requestExtensionAt = (request, requestAttr, responseAttr, name) => new Promise((resolve) => {
    const requestId = crypto.randomUUID();
    const observer = new MutationObserver(() => {
      try {
        const response = JSON.parse(document.documentElement.getAttribute(responseAttr) || '{}');
        if (response.requestId !== requestId) return;
        clearTimeout(timeout);
        observer.disconnect();
        resolve(response);
      } catch {
        // Wait for the complete extension response.
      }
    });
    const timeout = setTimeout(() => {
      observer.disconnect();
      resolve({ ok: false, error: `${name}이(가) 응답하지 않았습니다. 확장 프로그램과 이 페이지를 새로고침해 주세요.` });
    }, 3000);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: [responseAttr] });
    document.documentElement.setAttribute(requestAttr, JSON.stringify({ ...request, requestId }));
  });

  const pair = async (type, requestAttr, responseAttr, name) => {
    const result = await api('/api/admin/extension/pair', { method: 'POST', body: '{}' });
    const response = await requestExtensionAt({ type, deviceToken: result.device_token || '' }, requestAttr, responseAttr, name);
    if (!response.ok) throw new Error(response.error || `${name} 연결에 실패했습니다.`);
  };

  pairCollector.addEventListener('click', async () => {
    setBusy(true);
    setStatus(connectionStatus, '쿠팡 골드박스 수집기를 연결하는 중입니다.');
    try {
      await pair(
        'PAIR_COUPANG_COLLECTOR_DEVICE',
        'data-coupang-goldbox-collector-request',
        'data-coupang-goldbox-collector-response',
        '쿠팡 수집기',
      );
      setStatus(connectionStatus, '쿠팡 골드박스 수집기가 연결됐습니다. 검증 통과 상품만 텔레그램 승인 요청으로 보낼 수 있습니다.', 'success');
    } catch (error) {
      setStatus(connectionStatus, error.message || '쿠팡 수집기 연결에 실패했습니다.', 'error');
    } finally {
      setBusy(false);
    }
  });

  pairPublisher.addEventListener('click', async () => {
    setBusy(true);
    setStatus(connectionStatus, '쿠팡 네이버 발행 확장을 연결하는 중입니다.');
    try {
      await pair(
        'PAIR_COUPANG_PUBLISHER_DEVICE',
        'data-coupang-naver-publisher-request',
        'data-coupang-naver-publisher-response',
        '쿠팡 발행 확장',
      );
      setStatus(connectionStatus, '쿠팡 네이버 발행 확장이 연결됐습니다. 텔레그램 승인 후 카테고리 42 등록을 준비합니다.', 'success');
    } catch (error) {
      setStatus(connectionStatus, error.message || '쿠팡 발행 확장 연결에 실패했습니다.', 'error');
    } finally {
      setBusy(false);
    }
  });

  loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const value = password.value;
    if (!value) return;
    const submit = loginForm.querySelector('button[type=submit]');
    submit.disabled = true;
    setStatus(loginStatus, '로그인 중입니다.');
    try {
      const response = await fetch('/api/admin/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ password: value }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok || !payload.result?.csrf_token) throw new Error(payload.error || '로그인에 실패했습니다.');
      csrfToken = payload.result.csrf_token;
      password.value = '';
      enterDashboard();
      setStatus(connectionStatus, '쿠팡 수집기와 쿠팡 발행 확장을 각각 한 번 연결하면 됩니다.');
      loadDiagnostics();
      setInterval(loadDiagnostics, 15000);
    } catch (error) {
      password.value = '';
      setStatus(loginStatus, error.message === 'too_many_attempts' ? '로그인 시도가 잠시 제한됐습니다. 나중에 다시 시도해 주세요.' : '비밀번호를 확인해 주세요.', 'error');
    } finally {
      submit.disabled = false;
    }
  });

  logout.addEventListener('click', async () => {
    setBusy(true);
    try {
      await api('/api/admin/logout', { method: 'POST', body: '{}' });
    } catch (_) {
      // The session can already be expired; clear the client view either way.
    } finally {
      leaveDashboard('로그아웃했습니다.');
      setBusy(false);
    }
  });

  (async () => {
    try {
      const session = await api('/api/admin/session');
      csrfToken = session.csrf_token || '';
      if (!csrfToken) throw new Error('세션 정보가 없습니다.');
      enterDashboard();
      setStatus(connectionStatus, '쿠팡 수집기와 쿠팡 발행 확장을 각각 한 번 연결하면 됩니다.');
      loadDiagnostics();
      setInterval(loadDiagnostics, 15000);
    } catch (_) {
      leaveDashboard();
    }
  })();
})();
