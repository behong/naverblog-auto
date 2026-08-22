const GOLDBOX_URL = 'https://partners.coupang.com/#affiliate/ws/best/goldbox';
const BLOGAUTO_ORIGIN = 'https://blogauto.hongzi.us';
const MAX_BATCH_SIZE = 20;

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function setProgress(current, total) {
  chrome.action.setBadgeBackgroundColor({ color: '#0f766e' });
  chrome.action.setBadgeText({ text: total ? `${current}/${total}` : '' });
}

function waitForUrl(tabId, matcher, timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error('페이지 전환을 기다리는 시간이 초과됐습니다.'));
    }, timeoutMs);
    const listener = (changedTabId, changeInfo, tab) => {
      if (changedTabId === tabId && changeInfo.status === 'complete' && matcher.test(tab.url || '')) {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve(tab);
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.get(tabId).then((tab) => {
      if (matcher.test(tab.url || '')) {
        clearTimeout(timer);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve(tab);
      }
    }).catch(reject);
  });
}

function encodeDataUrl(payload) {
  const source = JSON.stringify(payload, null, 2);
  return `data:application/json;base64,${btoa(unescape(encodeURIComponent(source)))}`;
}

function enumerateGoldboxCandidates() {
  const maxBatchSize = 20;
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const imageUrl = (image) => image.currentSrc || image.getAttribute('src') || image.getAttribute('data-src') || '';
  const previewId = (value) => {
    let hash = 2166136261;
    for (const character of String(value)) {
      hash ^= character.charCodeAt(0);
      hash = Math.imul(hash, 16777619);
    }
    return `goldbox-preview-${(hash >>> 0).toString(16)}`;
  };
  const products = [];
  for (const image of document.querySelectorAll('img[alt="product"]')) {
    const card = image.parentElement?.parentElement || image.parentElement;
    const text = clean(card?.textContent);
    const marker = text.indexOf('링크 생성');
    const detail = marker >= 0 ? text.slice(marker + '링크 생성'.length) : text;
    const priceMatches = Array.from(detail.matchAll(/\d{1,3}(?:,\d{3})+\s*원|\d+\s*원/g));
    const first = priceMatches[0];
    const name = clean(first ? detail.slice(0, first.index).replace(/\d{1,3}%\s*$/, '') : '');
    const prices = priceMatches.map((match) => Number(match[0].replace(/[^0-9]/g, ''))).filter((value) => value > 0);
    const url = imageUrl(image);
    if (!name || !url || !prices.length || name.includes('…')) continue;
    products.push({
      candidate_id: previewId(`${name}|${prices[0]}|${prices[prices.length - 1]}`),
      product_name: name,
      preview_image_url: url,
      normal_price: prices[0],
      sale_price: prices[prices.length - 1],
    });
  }
  const seen = new Set();
  return products.filter((item) => !seen.has(item.candidate_id) && seen.add(item.candidate_id))
    .sort((left, right) => left.sale_price - right.sale_price || right.normal_price - left.normal_price)
    .slice(0, maxBatchSize);
}

function clickGoldboxCandidate(expectedCandidate) {
  const expectedId = String(expectedCandidate?.candidate_id || '');
  for (const image of document.querySelectorAll('img[alt="product"]')) {
    const card = image.parentElement?.parentElement || image.parentElement;
    const text = String(card?.textContent || '').replace(/\s+/g, ' ').trim();
    const marker = text.indexOf('링크 생성');
    const detail = marker >= 0 ? text.slice(marker + '링크 생성'.length) : text;
    const priceMatches = Array.from(detail.matchAll(/\d{1,3}(?:,\d{3})+\s*원|\d+\s*원/g));
    const first = priceMatches[0];
    const name = String(first ? detail.slice(0, first.index).replace(/\d{1,3}%\s*$/, '') : '').replace(/\s+/g, ' ').trim();
    const url = image.currentSrc || image.getAttribute('src') || image.getAttribute('data-src') || '';
    const prices = priceMatches.map((match) => Number(match[0].replace(/[^0-9]/g, ''))).filter((value) => value > 0);
    if (!name || !prices.length) continue;
    let hash = 2166136261;
    for (const character of `${name}|${prices[0]}|${prices[prices.length - 1]}`) { hash ^= character.charCodeAt(0); hash = Math.imul(hash, 16777619); }
    const currentId = `goldbox-preview-${(hash >>> 0).toString(16)}`;
    if (currentId !== expectedId) continue;
    const button = card?.querySelector('button.btn-generate-link') || Array.from(card?.querySelectorAll('button') || []).find((node) => String(node.textContent || '').trim() === '링크 생성');
    const candidate = { candidate_id: currentId, product_name: name, preview_image_url: url, normal_price: prices[0], sale_price: prices[prices.length - 1] };
    if (!button) return { ok: false, reason: 'generate_link_button_not_found', candidate };
    button.click();
    return { ok: true, candidate };
  }
  return { ok: false, reason: 'candidate_card_not_found' };
}

function captureGeneratedLink() {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const pageUrl = location.href;
  const parsed = new URL(pageUrl);
  const query = new URLSearchParams(parsed.hash.includes('?') ? parsed.hash.slice(parsed.hash.indexOf('?') + 1) : parsed.search);
  const links = (clean(document.body.innerText).match(/https:\/\/(?:link\.coupang\.com|coupa\.ng)\/[A-Za-z0-9_?=&%#./-]+/g) || [])
    .map((url) => url.replace(/[),.]+$/, ''));
  return {
    ok: Boolean(links.length),
    page_url: pageUrl,
    generated_urls: [...new Set(links)],
    product_id: query.get('product[productId]') || '',
    item_id: query.get('product[itemId]') || '',
    vendor_item_id: query.get('product[vendorItemId]') || '',
    product_name: query.get('product[title]') || '',
    normal_price: query.get('product[originPrice]') || '',
    sale_price: query.get('product[salesPrice]') || '',
    preview_image_url: query.get('product[image]') || '',
    travel: query.get('product[travel]') || '',
  };
}

async function execute(tabId, func, args = []) {
  const results = await chrome.scripting.executeScript({ target: { tabId }, func, args });
  return results[0]?.result || null;
}

function enumerateRenewedGoldboxCandidates() {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const money = (value) => Number(String(value || '').replace(/[^0-9]/g, '')) || 0;
  const candidates = [];
  for (const anchor of document.querySelectorAll('a[href*="/vp/products/"]')) {
    const card = anchor.querySelector('.discount-product-unit') || anchor;
    const title = clean(card.querySelector('.info_section__title, .info-section__title, [class*="title"]')?.textContent);
    const sale = money(card.querySelector('.price_info__discount')?.textContent);
    const normal = money(card.querySelector('.price_info__base')?.textContent);
    const href = anchor.href || '';
    const match = href.match(/\/vp\/products\/(\d+).*?[?&]itemId=(\d+).*?[?&]vendorItemId=(\d+)/);
    const image = card.querySelector('.discount-product-unit__product_image img')?.currentSrc || card.querySelector('img')?.currentSrc || card.querySelector('img')?.src || '';
    if (!title || !sale || !match) continue;
    const [, productId, itemId, vendorItemId] = match;
    const productImage = image.startsWith('//') ? `https:${image}` : image;
    const params = new URLSearchParams({ 'product[itemId]': itemId, 'product[productId]': productId, 'product[vendorItemId]': vendorItemId, 'product[title]': title, 'product[originPrice]': String(normal || sale), 'product[salesPrice]': String(sale), 'product[image]': productImage, 'product[travel]': 'false' });
    candidates.push({ candidate_id: `renewed-${productId}-${itemId}`, product_id: productId, item_id: itemId, vendor_item_id: vendorItemId, product_name: title, preview_image_url: productImage, normal_price: normal || sale, sale_price: sale, link_generation_url: `https://partners.coupang.com/#affiliate/ws/linkgeneration/PRODUCT/${productId}/${itemId}?${params.toString()}` });
  }
  return candidates.sort((a, b) => a.sale_price - b.sale_price).filter((item, index, all) => all.findIndex((other) => other.product_id === item.product_id) === index).slice(0, 20);
}

async function runBatch(tabId, options = {}) {
  // The previous single-link test leaves the tab on a link-generation route; always reset it first.
  await chrome.tabs.update(tabId, { url: GOLDBOX_URL });
  await sleep(3500);
  let initial = [];
  for (let attempt = 0; attempt < 3 && !initial.length; attempt += 1) {
    initial = await execute(tabId, enumerateGoldboxCandidates).catch(() => []);
    if (!Array.isArray(initial) || !initial.length) initial = await execute(tabId, enumerateRenewedGoldboxCandidates).catch(() => []);
    if (!initial.length) await sleep(2500);
  }
  if (!Array.isArray(initial) || !initial.length) throw new Error('골드박스 후보를 찾지 못했습니다. 리뉴얼 골드박스 로딩을 완료하지 못했습니다.');
  const results = [];
  setProgress(0, initial.length);
  for (let index = 0; index < initial.length; index += 1) {
    const candidate = initial[index];
    try {
      if (candidate.link_generation_url) {
        await chrome.tabs.update(tabId, { url: candidate.link_generation_url });
        await sleep(1800);
      } else {
        await chrome.tabs.update(tabId, { url: GOLDBOX_URL });
        await waitForUrl(tabId, /#affiliate\/ws\/best\/goldbox/);
        await sleep(700);
        const clicked = await execute(tabId, clickGoldboxCandidate, [candidate]);
        if (!clicked?.ok) throw new Error(clicked?.reason || 'candidate_click_failed');
        await waitForUrl(tabId, /#affiliate\/ws\/linkgeneration\//);
      }
      await sleep(1800);
      const captured = await execute(tabId, captureGeneratedLink);
      results.push({ candidate, ...captured, approval_only: true, publish_executed: false });
    } catch (error) {
      results.push({ candidate, ok: false, error: error instanceof Error ? error.message : String(error) });
    }
    setProgress(index + 1, initial.length);
  }
  const payload = {
    source: 'coupang-partners-goldbox-batch-link-generation',
    captured_at: new Date().toISOString(),
    publish_executed: false,
    approval_only: true,
    results,
  };
  await chrome.storage.local.set({
    coupangGoldboxPartnerLinkResults: results,
    coupangGoldboxPartnerLinkResultsUpdatedAt: Date.now(),
  });
  if (options.save !== false) {
    await chrome.downloads.download({
      url: encodeDataUrl(payload),
      filename: `coupang-goldbox-batch-link-results-${new Date().toISOString().slice(0, 10)}.json`,
      saveAs: true,
    });
  }
  setProgress(0, 0);
  return { total: initial.length, success: results.filter((item) => item.ok).length, failed: results.filter((item) => !item.ok).length };
}

let scheduledRunActive = false;

function nextLocalOccurrence(hour) {
  const now = new Date();
  const next = new Date(now);
  next.setHours(hour, 0, 0, 0);
  if (next <= now) next.setDate(next.getDate() + 1);
  return next.getTime();
}

async function ensureGoldboxTab() {
  const tabs = await chrome.tabs.query({ url: ['https://partners.coupang.com/*'] });
  const existing = tabs.find((tab) => Number.isInteger(tab.id));
  if (existing?.id) {
    await chrome.tabs.update(existing.id, { active: true, url: GOLDBOX_URL });
    return existing.id;
  }
  const created = await chrome.tabs.create({ url: GOLDBOX_URL, active: false });
  if (!created.id) throw new Error('골드박스 자동화 탭을 만들지 못했습니다.');
  return created.id;
}

async function extractAutoDetail(tabId) {
  return execute(tabId, () => {
    const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
    const text = clean(document.body.innerText);
    const title = clean(document.querySelector('.prod-buy-header__title')?.textContent || document.querySelector('h1')?.textContent || document.title).replace(/\s*[|｜-]\s*쿠팡.*$/i, '');
    const id = location.pathname.match(/\/vp\/products\/(\d+)/)?.[1] || '';
    const prices = [...text.matchAll(/(?<!\d)(\d{1,3}(?:,\d{3})+|\d+)\s*원/g)].map((m) => Number(m[1].replace(/,/g, ''))).filter((v) => v > 0);
    const uniquePrices = [...new Set(prices)];
    const imageUrls = [...document.querySelectorAll('.prod-image-container img, .prod-image img, img[class*="prod-image"], img[class*="product-image"], img[data-img-src], img[data-origin-image], meta[property="og:image"], meta[name="twitter:image"], script[type="application/ld+json"]')].flatMap((node) => {
      const raw = [node.getAttribute?.('content'), node.currentSrc, node.src, node.getAttribute?.('data-src'), node.getAttribute?.('data-img-src'), node.getAttribute?.('data-origin-image')].filter(Boolean);
      if (node.tagName === 'SCRIPT') { try { const data = JSON.parse(node.textContent || '{}'); return raw.concat(Array.isArray(data.image) ? data.image : [data.image]); } catch (_) {} }
      return raw;
    }).filter((url, i, all) => /^https:\/\/.*coupangcdn\.com\//i.test(String(url)) && !/(\/common\/|logo|sprite|icon)/i.test(String(url)) && all.indexOf(url) === i);
    const composition = clean((text.match(/(?:개당 중량\s*×\s*수량|중량\s*×\s*수량):\s*([^\n]{1,80})/i) || [])[1] || (title.match(/\d+(?:\.\d+)?\s*(?:kg|g|L|ml|개|입|팩|세트)/i) || [])[0] || '');
    const condition = /와우/.test(text) ? '와우회원 혜택 적용 시' : (/쿠폰/.test(text) ? '쿠폰 적용 시' : '');
    return { product_id: id, product_name: title, composition, product_page_url: location.href, normal_price: uniquePrices[0] || 0, sale_price: uniquePrices[1] || uniquePrices[0] || 0, conditional_price: uniquePrices[2] || uniquePrices[1] || uniquePrices[0] || 0, price_condition: condition, source_image_url: imageUrls[0] || '', source_image_urls: imageUrls.slice(0, 4), features: [], audiences: [], source_image_verified: false };
  });
}

async function verifyAutoImage(url) {
  const source = String(url || '').trim();
  if (!/^https:\/\/.*coupangcdn\.com\//i.test(source) || /(\/common\/|logo|sprite|icon)/i.test(source)) return { ok: false, reason: 'disallowed_image_url', url: source };
  const attempts = [source, `${BLOGAUTO_ORIGIN}/api/coupang/image?url=${encodeURIComponent(source)}`];
  const diagnostics = [];
  for (const candidate of attempts) {
    try {
      const response = await fetch(candidate, { cache: 'no-store', credentials: 'omit' });
      const contentType = String(response.headers.get('content-type') || '').toLowerCase();
      const size = (await response.blob()).size;
      diagnostics.push({ status: response.status, content_type: contentType, size, via_proxy: candidate !== source });
      if (response.ok && contentType.startsWith('image/') && size >= 4096) return { ok: true, via_proxy: candidate !== source, diagnostics };
    } catch (error) { diagnostics.push({ error: error?.message || String(error), via_proxy: candidate !== source }); }
  }
  return { ok: false, reason: 'image_fetch_failed', url: source, diagnostics };
}

async function recordScheduledDiagnostic(payload, deviceToken) {
  try {
    await fetch(`${BLOGAUTO_ORIGIN}/api/coupang/extension/diagnostic`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Naver-Draft-Device': deviceToken },
      body: JSON.stringify({ run_id: payload.run_id || undefined, ...payload, context: { source: 'extension-scheduled-worker', ...(payload.context || {}) } }),
      cache: 'no-store',
    });
  } catch (error) {
    console.warn('[Coupang] diagnostic upload failed:', error?.message || error);
  }
}

async function requestAutoApproval(detail, affiliateUrl, deviceToken) {
  const imageVerified = await verifyAutoImage(detail.source_image_url);
  if (!imageVerified.ok) return { ok: false, error: '원본 대표 이미지를 검증하지 못했습니다.', image_diagnostics: imageVerified };
  const prices = [detail.normal_price, detail.sale_price, detail.conditional_price].map(Number).filter((value) => value > 0).sort((a, b) => b - a);
  const candidate = {
    product_id: detail.product_id,
    product_name: detail.product_name,
    composition: detail.composition || '상품 구성은 상세 페이지에서 확인',
    product_url: detail.product_page_url,
    affiliate_url: affiliateUrl,
    original_image_url: detail.source_image_url,
    normal_price: prices[0],
    sale_price: prices[1] || prices[0],
    conditional_price: prices[2] || prices[1] || prices[0],
    price_condition: detail.price_condition || '판매 조건은 상세 페이지에서 확인',
    description: '', features: [], audiences: [], source_image_verified: true,
  };
  const response = await fetch(`${BLOGAUTO_ORIGIN}/api/coupang/collector/approval`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Naver-Draft-Device': deviceToken }, body: JSON.stringify({ candidate, ttl_minutes: 30 }), cache: 'no-store' });
  const body = await response.json().catch(() => ({}));
  return response.ok && body?.ok ? { ok: true } : { ok: false, error: body?.error || '텔레그램 승인 요청을 만들지 못했습니다.' };
}

async function runScheduledGoldbox(limit = 4) {
  if (scheduledRunActive) return { ok: false, error: '이미 자동 수집이 실행 중입니다.' };
  scheduledRunActive = true;
  let runId = '';
  try {
    const localState = await chrome.storage.local.get('coupangCollectorDeviceToken');
    const syncState = await chrome.storage.sync.get('coupangCollectorDeviceToken');
    const deviceToken = String(localState.coupangCollectorDeviceToken || syncState.coupangCollectorDeviceToken || '').trim();
    console.info('[Coupang] scheduled run token:', deviceToken.length >= 24 ? 'available' : 'missing');
    if (deviceToken.length >= 24 && localState.coupangCollectorDeviceToken !== deviceToken) {
      await chrome.storage.local.set({ coupangCollectorDeviceToken: deviceToken });
    }
    if (deviceToken.length < 24) throw new Error('쿠팡 수집기 연결 정보가 없습니다. 최초 1회만 관리자 페이지에서 연결해 주세요.');
    const tabId = await ensureGoldboxTab();
    runId = crypto.randomUUID();
    await recordScheduledDiagnostic({ run_id: runId, status: 'STARTED', step: '예약 워커 시작', context: { limit } }, deviceToken);
    console.info('[Coupang] scheduled run starting on tab', tabId);
    await recordScheduledDiagnostic({ run_id: runId, status: 'DISCOVERED', step: '골드박스 탭 생성 완료', context: { tab_id: tabId } }, deviceToken);
    const summary = await runBatch(tabId, { save: false });
    console.info('[Coupang] scheduled run summary:', summary);
    await recordScheduledDiagnostic({ run_id: runId, status: 'LINK_CREATED', step: '골드박스 후보·파트너스 링크 처리 완료', context: { summary } }, deviceToken);
    const stored = await chrome.storage.local.get('coupangGoldboxPartnerLinkResults');
    const results = Array.isArray(stored.coupangGoldboxPartnerLinkResults) ? stored.coupangGoldboxPartnerLinkResults.filter((item) => item?.ok && item?.product_id && item?.generated_urls?.[0]) : [];
    const outcomes = [];
    for (const item of results.slice(0, Math.max(1, Math.min(10, Number(limit) || 4)))) {
      const detailUrl = `https://www.coupang.com/vp/products/${encodeURIComponent(item.product_id)}?itemId=${encodeURIComponent(item.item_id || '')}&vendorItemId=${encodeURIComponent(item.vendor_item_id || '')}`;
      await chrome.tabs.update(tabId, { url: detailUrl });
      await waitForUrl(tabId, /https:\/\/www\.coupang\.com\/vp\/products\//);
      await sleep(1200);
      const detail = await extractAutoDetail(tabId);
      if (!detail.source_image_url && item.preview_image_url) detail.source_image_url = item.preview_image_url;
      const approval = await requestAutoApproval(detail, item.generated_urls[0], String(deviceToken));
      outcomes.push({ product_id: item.product_id, approval });
      const imageDiagnostics = approval.image_diagnostics || null;
      const diagnosticMessage = approval.ok ? '' : `${approval.error}${imageDiagnostics ? ` [image=${JSON.stringify(imageDiagnostics).slice(0, 1200)}]` : ''}`;
      await recordScheduledDiagnostic({ run_id: runId, status: approval.ok ? 'AWAITING_APPROVAL' : 'FAILED', step: approval.ok ? '텔레그램 승인 요청 생성' : '텔레그램 승인 요청 실패', product_id: item.product_id, product_name: detail.product_name, error_message: diagnosticMessage, context: { approval, image_diagnostics: imageDiagnostics } }, deviceToken);
    }
    await recordScheduledDiagnostic({ run_id: runId, status: 'AWAITING_APPROVAL', step: '예약 워커 완료·승인 대기', context: { outcomes } }, deviceToken);
    return { ok: true, summary, outcomes };
  } catch (error) {
    const state = await chrome.storage.local.get('coupangCollectorDeviceToken');
    const syncState = await chrome.storage.sync.get('coupangCollectorDeviceToken');
    const token = String(state.coupangCollectorDeviceToken || syncState.coupangCollectorDeviceToken || '').trim();
    if (token.length >= 24) await recordScheduledDiagnostic({ run_id: runId || undefined, status: 'FAILED', step: '예약 워커 예외 종료', error_message: error?.message || String(error) }, token);
    throw error;
  } finally { scheduledRunActive = false; }
}

function installAutoAlarms() {
  for (const hour of [7, 12, 18]) chrome.alarms.create(`coupang-goldbox-${hour}`, { when: nextLocalOccurrence(hour), periodInMinutes: 1440 });
}

async function scheduleOneTimeSmokeTest() {
  const [localState, syncState, alarm, completed] = await Promise.all([
    chrome.storage.local.get('coupangCollectorDeviceToken'),
    chrome.storage.sync.get('coupangCollectorDeviceToken'),
    chrome.alarms.get('coupang-goldbox-test'),
    chrome.storage.local.get('coupangAutoSmokeTestCompleted'),
  ]);
  const deviceToken = String(localState.coupangCollectorDeviceToken || syncState.coupangCollectorDeviceToken || '').trim();
  if (deviceToken.length < 24 || completed.coupangAutoSmokeTestCompleted === '0.2.5') return;
  if (!alarm) {
    console.info('[Coupang] scheduling smoke test because no test alarm exists');
    chrome.alarms.create('coupang-goldbox-test', { when: Date.now() + 60 * 1000 });
  }
}

scheduleOneTimeSmokeTest().catch((error) => console.error('Coupang smoke test scheduling failed', error));
chrome.runtime.onInstalled.addListener(() => {
  installAutoAlarms();
  chrome.alarms.create('coupang-goldbox-test', { when: Date.now() + 60 * 1000 });
});
chrome.runtime.onStartup.addListener(installAutoAlarms);
chrome.alarms.onAlarm.addListener((alarm) => {
  if (!/^coupang-goldbox-/.test(alarm.name)) return;
  if (alarm.name === 'coupang-goldbox-test') {
    runScheduledGoldbox(1).then((result) => {
      console.info('[Coupang] automatic test finished:', result);
      return chrome.storage.local.set({ coupangAutoSmokeTestCompleted: '0.2.5' });
    }).catch((error) => console.error('Coupang automatic test failed', error));
    return;
  }
  const hour = Number(String(alarm.name).split('-').pop());
  const limit = hour === 12 ? 2 : 4;
  runScheduledGoldbox(limit).catch((error) => console.error('Coupang scheduled run failed', error));
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === 'COUPANG_COLLECTOR_PAIR_DEVICE') {
    (async () => {
      try {
        const origin = new URL(sender.url || sender.tab?.url || '').origin;
        const token = String(message.deviceToken || '').trim();
        if (origin !== 'https://blogauto.hongzi.us' || token.length < 24) throw new Error('쿠팡 수집기 연결 요청이 올바르지 않습니다.');
        await chrome.storage.local.set({ coupangCollectorDeviceToken: token, coupangCollectorPairTabId: sender.tab?.id || null });
        await chrome.storage.sync.set({ coupangCollectorDeviceToken: token });
        // 연결 직후에는 표식 상태와 관계없이 1건 자동 테스트를 예약한다.
        chrome.alarms.create('coupang-goldbox-test', { when: Date.now() + 60 * 1000 });
        sendResponse({ ok: true });
      } catch (error) {
        sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) });
      }
    })();
    return true;
  }
  if (message?.type !== 'START_GOLDBOX_LINK_BATCH') return undefined;
  runBatch(message.tabId)
    .then((summary) => sendResponse({ ok: true, summary }))
    .catch((error) => {
      setProgress(0, 0);
      sendResponse({ ok: false, error: error instanceof Error ? error.message : String(error) });
    });
  return true;
});
