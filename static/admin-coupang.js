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
  const overviewRuns = document.querySelector('#overviewRuns');
  const overviewNext = document.querySelector('#overviewNext');
  const overviewQueue = document.querySelector('#overviewQueue');
  const overviewMode = document.querySelector('#overviewMode');
  const overviewSuccess = document.querySelector('#overviewSuccess');
  const overviewUpdated = document.querySelector('#overviewUpdated');
  const overviewServiceNote = document.querySelector('#overviewServiceNote');
  const overviewQueueNote = document.querySelector('#overviewQueueNote');
  const overviewNextNote = document.querySelector('#overviewNextNote');
  const overviewSuccessLabel = document.querySelector('#overviewSuccessLabel');
  const overviewSuccessTime = document.querySelector('#overviewSuccessTime');
  const overviewSchedule = document.querySelector('#overviewSchedule');
  const overviewAttention = document.querySelector('#overviewAttention');
  const overviewAttentionCount = document.querySelector('#overviewAttentionCount');
  const refreshOverview = document.querySelector('#refreshOverview');

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

  const formatTime = (value) => {
    if (!value) return '없음';
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString('ko-KR', { dateStyle: 'short', timeStyle: 'short' });
  };

  const loadOverview = async () => {
    if (!overviewRuns) return;
    try {
      const data = await api('/api/admin/coupang/overview');
      const runs = Array.isArray(data.today_runs) ? data.today_runs : [];
      const queue = data.queue || {};
      const attention = runs.filter((row) => ['FAILED', 'ERROR'].includes(String(row.status || '').toUpperCase())).slice(0, 5);
      overviewRuns.textContent = `${runs.length}건 실행`;
      overviewNext.textContent = formatTime(data.next_schedule);
      overviewQueue.textContent = `${Number(queue.NOT_STARTED || 0) + Number(queue.PUBLISHING || 0)}건 대기`;
      overviewMode.textContent = data.auto_publish ? '자동 공개 설정' : '승인 대기';
      overviewServiceNote.textContent = data.auto_publish ? '검증 통과 항목을 승인 없이 순차 발행합니다.' : '검증 통과 항목을 승인 후 발행합니다.';
      overviewQueueNote.textContent = `대기 ${Number(queue.NOT_STARTED || 0)} · 발행 중 ${Number(queue.PUBLISHING || 0)} · 확인 필요 ${attention.length}`;
      overviewNextNote.textContent = `다음 골드박스 수집 예정 · ${formatTime(data.next_schedule)}`;
      const success = data.recent_success;
      overviewSuccessLabel.textContent = success ? '공개 완료' : '공개 대기';
      overviewSuccessTime.textContent = success ? `${success.product_name || '최근 상품'} · ${formatTime(success.published_at)}` : '최근 성공 URL 없음';
      overviewSuccess.textContent = success?.naver_post_url ? '최근 공개 글 열기' : '';
      overviewSuccess.href = success?.naver_post_url || '#';
      overviewSuccess.hidden = !success?.naver_post_url;
      overviewAttentionCount.textContent = `${attention.length}건`;
      overviewSchedule.innerHTML = [
        ['07:00 오전 골드박스', '예정 4건', data.today ? '오늘 일정' : '일정'],
        ['12:00 정오 골드박스', '예정 2건', '일정'],
        ['18:00 저녁 골드박스', '예정 4건', '일정'],
      ].map(([title, detail, status], index) => `<div class="schedule-row"><div><strong>${title}</strong><small>${detail}</small></div><span class="status-pill ${index === 0 && runs.length ? 'done' : ''}">${index === 0 && runs.length ? '준비 완료' : status}</span></div>`).join('');
      overviewAttention.innerHTML = attention.length ? attention.map((row) => `<div class="attention-row"><div><strong>${row.product_name || '상품 정보 없음'}</strong><small>${row.step || '자동 발행'} · ${row.error_message || row.error_code || '오류가 기록되었습니다.'}</small></div><time>${formatTime(row.updated_at)}</time></div>`).join('') : '<div class="schedule-row"><div><strong>확인 필요한 항목이 없습니다.</strong><small>오늘 자동 실행이 정상적으로 진행 중입니다.</small></div><span class="status-pill done">정상</span></div>';
      overviewUpdated.textContent = `${data.today} 기준 · 마지막 조회 ${formatTime(new Date().toISOString())}`;
    } catch (error) {
      overviewUpdated.textContent = `운영 현황을 불러오지 못했습니다: ${error.message || error}`;
    }
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

  refreshOverview?.addEventListener('click', () => loadOverview());

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
      loadOverview();
      loadDiagnostics();
      setInterval(() => { loadOverview(); loadDiagnostics(); }, 15000);
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
      loadOverview();
      loadDiagnostics();
      setInterval(() => { loadOverview(); loadDiagnostics(); }, 15000);
    } catch (_) {
      leaveDashboard();
    }
  })();
})();
