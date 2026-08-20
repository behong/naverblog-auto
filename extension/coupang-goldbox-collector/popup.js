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
  const productIdFrom = (value) => {
    const source = String(value || '');
    const match = source.match(/(?:\/products\/|[?&](?:productId|product_id|itemId|item_id)=|data-(?:product|item)-id=["']?)(\d+)/i);
    return match ? match[1] : '';
  };
  const priceFromText = (text) => {
    const matches = clean(text).match(/\d{1,3}(?:,\d{3})+\s*원|\d+\s*원/g) || [];
    const values = matches
      .map((value) => Number(value.replace(/[^0-9]/g, '')))
      .filter((value) => Number.isFinite(value) && value > 0);
    return values.length ? Math.min(...values) : null;
  };
  const attribute = (element, names) => {
    for (const name of names) {
      const value = element?.getAttribute?.(name);
      if (value) return value;
    }
    return '';
  };
  const cardFor = (element) => {
    let cursor = element;
    for (let depth = 0; cursor && depth < 8; depth += 1, cursor = cursor.parentElement) {
      const text = clean(cursor.textContent);
      if (text.length >= 8 && text.length <= 3500 && cursor.querySelector('img')) return cursor;
    }
    return element.parentElement || element;
  };
  const imageFor = (card) => {
    for (const image of card.querySelectorAll('img')) {
      const value = attribute(image, ['src', 'data-src', 'data-original', 'data-lazy-src']);
      const url = absolute(value);
      if (url.startsWith('https://')) return { url, alt: clean(image.getAttribute('alt')) };
    }
    return { url: '', alt: '' };
  };
  const diagnosticUrl = (value) => {
    try {
      const parsed = new URL(value, location.href);
      return `${parsed.origin}${parsed.pathname}`;
    } catch (_) {
      return '';
    }
  };
  const sourceElements = document.querySelectorAll(
    'a[href], [data-product-id], [data-productid], [data-item-id], [data-itemid], [data-product-url]'
  );
  const seen = new Set();
  const candidates = [];
  const previewId = (value) => {
    let hash = 2166136261;
    for (const character of String(value)) {
      hash ^= character.charCodeAt(0);
      hash = Math.imul(hash, 16777619);
    }
    return `goldbox-preview-${(hash >>> 0).toString(16)}`;
  };
  const productPriceValues = (text) => (clean(text).match(/\d{1,3}(?:,\d{3})+\s*원|\d+\s*원/g) || [])
    .map((value) => Number(value.replace(/[^0-9]/g, '')))
    .filter((value) => Number.isFinite(value) && value > 0);

  // Goldbox cards use image elements and a nearby '상품정보 / 링크 생성' control instead of product anchors.
  for (const imageElement of document.querySelectorAll('img[alt="product"]')) {
    const card = cardFor(imageElement);
    const text = clean(card.textContent);
    const imageUrl = absolute(attribute(imageElement, ['src', 'data-src', 'data-original', 'data-lazy-src']));
    const titleMatch = text.match(/링크\s*생성\s*(.+?)\s*(?:\d{1,3}%\s*)?\d{1,3}(?:,\d{3})+\s*원/i);
    const productName = clean(titleMatch ? titleMatch[1] : '');
    const prices = productPriceValues(text);
    if (!productName || !imageUrl || !prices.length) continue;
    const candidateId = previewId(`${productName}|${imageUrl}`);
    if (seen.has(candidateId)) continue;
    seen.add(candidateId);
    candidates.push({
      candidate_id: candidateId,
      product_id: '',
      product_name: productName,
      product_url: '',
      preview_image_url: imageUrl,
      displayed_normal_price: prices[0],
      displayed_sale_price: prices[prices.length - 1],
      source_image_verified: false,
      requires_product_detail_verification: true,
      requires_partner_link_generation: true,
    });
  }

  for (const element of sourceElements) {
    const card = cardFor(element);
    const link = element.closest('a[href]') || card.querySelector('a[href]');
    const rawUrl = attribute(element, ['href', 'data-product-url', 'data-url']) || attribute(link, ['href']);
    const productId = productIdFrom(rawUrl) || productIdFrom(JSON.stringify(element.dataset || {})) || productIdFrom(JSON.stringify(card.dataset || {}));
    if (!productId || seen.has(productId)) continue;
    const image = imageFor(card);
    const text = clean(card.textContent);
    const productName = clean(
      image.alt ||
      attribute(element, ['title', 'aria-label', 'data-product-name']) ||
      Array.from(card.querySelectorAll('[title], h1, h2, h3, h4, strong, b, p, span'))
        .map((node) => node.getAttribute('title') || node.textContent)
        .map(clean)
        .find((value) => value.length >= 3 && !/\d+\s*원/.test(value)) || ''
    );
    if (!productName || !image.url) continue;
    seen.add(productId);
    candidates.push({
      product_id: productId,
      product_name: productName,
      product_url: absolute(rawUrl) || `https://www.coupang.com/vp/products/${productId}`,
      original_image_url: image.url,
      displayed_price: priceFromText(text),
      source_image_verified: false,
    });
  }
  const sampleAnchors = Array.from(document.querySelectorAll('a[href]')).slice(0, 30).map((anchor) => ({
    href: diagnosticUrl(anchor.getAttribute('href')),
    text: clean(anchor.textContent).slice(0, 180),
    title: clean(anchor.getAttribute('title') || anchor.getAttribute('aria-label')).slice(0, 180),
    class_name: clean(anchor.className).slice(0, 180),
  }));
  const sampleImages = Array.from(document.querySelectorAll('img')).slice(0, 45).map((image) => {
    const parent = image.parentElement;
    return {
      src: diagnosticUrl(attribute(image, ['src', 'data-src', 'data-original', 'data-lazy-src'])),
      alt: clean(image.getAttribute('alt')).slice(0, 180),
      parent_class: clean(parent?.className).slice(0, 180),
      nearby_text: clean(parent?.parentElement?.textContent).slice(0, 240),
    };
  });
  return {
    frame_url: location.href,
    diagnostics: {
      anchors: document.querySelectorAll('a[href]').length,
      product_attributes: document.querySelectorAll('[data-product-id], [data-productid], [data-item-id], [data-itemid], [data-product-url]').length,
      images: document.querySelectorAll('img').length,
      iframes: document.querySelectorAll('iframe').length,
    },
    sample_anchors: sampleAnchors,
    sample_images: sampleImages,
    candidates,
  };
}

async function downloadJson(payload, filename) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
  const objectUrl = URL.createObjectURL(blob);
  try {
    await chrome.downloads.download({ url: objectUrl, filename, saveAs: true });
  } finally {
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
}

collectButton.addEventListener('click', async () => {
  collectButton.disabled = true;
  setStatus('현재 골드박스 화면과 포함된 프레임을 확인하는 중입니다…');
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !String(tab.url || '').startsWith('https://partners.coupang.com/')) {
      throw new Error('쿠팡 파트너스 골드박스 탭에서만 사용할 수 있습니다.');
    }
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id, allFrames: true },
      func: scrapeGoldboxCandidates,
    });
    const seen = new Set();
    const candidates = [];
    const frames = [];
    for (const result of results) {
      const payload = result.result || {};
      frames.push({
        frame_id: result.frameId,
        frame_url: payload.frame_url || '',
        diagnostics: payload.diagnostics || {},
        sample_anchors: Array.isArray(payload.sample_anchors) ? payload.sample_anchors : [],
        sample_images: Array.isArray(payload.sample_images) ? payload.sample_images : [],
      });
      for (const candidate of Array.isArray(payload.candidates) ? payload.candidates : []) {
        const identity = String(candidate?.product_id || candidate?.candidate_id || '');
        if (identity && !seen.has(identity)) {
          seen.add(identity);
          candidates.push(candidate);
        }
      }
    }
    const date = new Date().toISOString().slice(0, 10);
    if (!candidates.length) {
      await downloadJson({ source: 'coupang-partners-goldbox', captured_at: new Date().toISOString(), page_url: tab.url, frames, candidates: [] }, `coupang-goldbox-diagnostic-${date}.json`);
      setStatus('후보 0건입니다. 화면 진단 JSON을 저장했습니다. 이 파일을 보내주시면 실제 카드 구조에 맞춰 보완하겠습니다.');
      return;
    }
    await downloadJson({ source: 'coupang-partners-goldbox', captured_at: new Date().toISOString(), page_url: tab.url, frames, candidates }, `coupang-goldbox-candidates-${date}.json`);
    setStatus(`${candidates.length}건 후보를 JSON 파일로 저장했습니다. 가격·링크·원본 이미지는 다음 검증 단계에서 다시 확인합니다.`);
  } catch (error) {
    setStatus(`저장하지 않았습니다: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    collectButton.disabled = false;
  }
});
