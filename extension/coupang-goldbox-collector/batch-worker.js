const GOLDBOX_URL = 'https://partners.coupang.com/#affiliate/ws/best/goldbox';
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

async function runBatch(tabId) {
  // The previous single-link test leaves the tab on a link-generation route; always reset it first.
  await chrome.tabs.update(tabId, { url: GOLDBOX_URL });
  await waitForUrl(tabId, /#affiliate\/ws\/best\/goldbox/);
  await sleep(900);
  const initial = await execute(tabId, enumerateGoldboxCandidates);
  if (!Array.isArray(initial) || !initial.length) throw new Error('골드박스 후보를 찾지 못했습니다. 목록을 다시 연 뒤 시도해 주세요.');
  const results = [];
  setProgress(0, initial.length);
  for (let index = 0; index < initial.length; index += 1) {
    const candidate = initial[index];
    await chrome.tabs.update(tabId, { url: GOLDBOX_URL });
    await waitForUrl(tabId, /#affiliate\/ws\/best\/goldbox/);
    await sleep(700);
    const clicked = await execute(tabId, clickGoldboxCandidate, [candidate]);
    if (!clicked?.ok) {
      results.push({ candidate, ok: false, error: clicked?.reason || 'candidate_click_failed' });
      setProgress(index + 1, initial.length);
      continue;
    }
    try {
      await waitForUrl(tabId, /#affiliate\/ws\/linkgeneration\//);
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
  await chrome.downloads.download({
    url: encodeDataUrl(payload),
    filename: `coupang-goldbox-batch-link-results-${new Date().toISOString().slice(0, 10)}.json`,
    saveAs: true,
  });
  setProgress(0, 0);
  return { total: initial.length, success: results.filter((item) => item.ok).length, failed: results.filter((item) => !item.ok).length };
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === 'COUPANG_COLLECTOR_PAIR_DEVICE') {
    (async () => {
      try {
        const origin = new URL(sender.url || sender.tab?.url || '').origin;
        const token = String(message.deviceToken || '').trim();
        if (origin !== 'https://blogauto.hongzi.us' || token.length < 24) throw new Error('쿠팡 수집기 연결 요청이 올바르지 않습니다.');
        await chrome.storage.local.set({ coupangCollectorDeviceToken: token, coupangCollectorPairTabId: sender.tab?.id || null });
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
