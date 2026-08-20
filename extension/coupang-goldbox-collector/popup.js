const collectButton = document.getElementById('collect');
const statusElement = document.getElementById('status');

function setStatus(message) {
  statusElement.textContent = message;
}

function scrapeGoldboxCandidates() {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const absolute = (href) => {
    try {
      return new URL(href, location.href).href;
    } catch (_) {
      return '';
    }
  };
  const productIdFromUrl = (url) => {
    const match = String(url || '').match(/\/products\/(\d+)/);
    return match ? match[1] : '';
  };
  const priceFromText = (text) => {
    const matches = clean(text).match(/\d{1,3}(?:,\d{3})+\s*원|\d+\s*원/g) || [];
    const values = matches
      .map((value) => Number(value.replace(/[^0-9]/g, '')))
      .filter((value) => Number.isFinite(value) && value > 0);
    return values.length ? Math.min(...values) : null;
  };
  const cardFor = (element) => {
    let cursor = element;
    for (let depth = 0; cursor && depth < 6; depth += 1, cursor = cursor.parentElement) {
      const text = clean(cursor.textContent);
      if (text.length >= 8 && text.length <= 2400 && cursor.querySelector('img')) {
        return cursor;
      }
    }
    return element.parentElement || element;
  };

  const seen = new Set();
  const candidates = [];
  for (const anchor of document.querySelectorAll('a[href]')) {
    const productUrl = absolute(anchor.getAttribute('href'));
    const productId = productIdFromUrl(productUrl);
    if (!productId || seen.has(productId)) {
      continue;
    }
    const card = cardFor(anchor);
    const image = card.querySelector('img[src]');
    const imageUrl = image ? absolute(image.getAttribute('src')) : '';
    const text = clean(card.textContent);
    const productName = clean(
      (image && image.getAttribute('alt')) ||
      anchor.getAttribute('title') ||
      anchor.getAttribute('aria-label') ||
      Array.from(card.querySelectorAll('[title], h1, h2, h3, h4, strong, b, p, span'))
        .map((node) => node.getAttribute('title') || node.textContent)
        .map(clean)
        .find((value) => value.length >= 3 && !/\d+\s*원/.test(value)) || ''
    );
    if (!productName || !imageUrl) {
      continue;
    }
    seen.add(productId);
    candidates.push({
      product_id: productId,
      product_name: productName,
      product_url: productUrl,
      original_image_url: imageUrl,
      displayed_price: priceFromText(text),
      source_image_verified: false,
    });
  }
  return {
    source: 'coupang-partners-goldbox',
    captured_at: new Date().toISOString(),
    page_url: location.href,
    candidates,
  };
}

async function downloadCandidates(payload) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const objectUrl = URL.createObjectURL(blob);
  try {
    await chrome.downloads.download({
      url: objectUrl,
      filename: `coupang-goldbox-candidates-${new Date().toISOString().slice(0, 10)}.json`,
      saveAs: true,
    });
  } finally {
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
}

collectButton.addEventListener('click', async () => {
  collectButton.disabled = true;
  setStatus('현재 골드박스 화면을 확인하는 중입니다…');
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !String(tab.url || '').startsWith('https://partners.coupang.com/')) {
      throw new Error('쿠팡 파트너스 골드박스 탭에서만 사용할 수 있습니다.');
    }
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: scrapeGoldboxCandidates,
    });
    const payload = results[0]?.result;
    const count = Array.isArray(payload?.candidates) ? payload.candidates.length : 0;
    if (!count) {
      throw new Error('상품 후보를 읽지 못했습니다. 골드박스 목록이 완전히 표시된 뒤 다시 시도해 주세요.');
    }
    await downloadCandidates(payload);
    setStatus(`${count}건 후보를 JSON 파일로 저장했습니다. 가격·링크·원본 이미지는 다음 검증 단계에서 다시 확인합니다.`);
  } catch (error) {
    setStatus(`저장하지 않았습니다: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    collectButton.disabled = false;
  }
});
