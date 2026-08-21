const collectButton = document.getElementById('collect');
const inspectButton = document.getElementById('inspect');
const generateButton = document.getElementById('generate');
const batchButton = document.getElementById('batch');
const detailButton = document.getElementById('detail');
const approvalButton = document.getElementById('approval');
const statusElement = document.getElementById('status');
const BLOGAUTO_ORIGIN = 'https://blogauto.hongzi.us';

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
  const previewDiagnostics = { product_images_seen: 0, missing_text: 0, missing_title: 0, missing_price: 0, missing_image: 0 };

  // Goldbox cards use image elements and a nearby '상품정보 / 링크 생성' control instead of product anchors.
  for (const imageElement of document.querySelectorAll('img[alt="product"]')) {
    previewDiagnostics.product_images_seen += 1;
    // The actual card text is on the grandparent of .product-picture in the Goldbox page.
    const card = imageElement.parentElement?.parentElement || cardFor(imageElement);
    const text = clean(card?.textContent);
    const imageUrl = absolute(attribute(imageElement, ['src', 'data-src', 'data-original', 'data-lazy-src']));
    if (!text) {
      previewDiagnostics.missing_text += 1;
      continue;
    }
    const marker = text.indexOf('링크 생성');
    const detailText = marker >= 0 ? text.slice(marker + '링크 생성'.length) : text;
    const priceMatches = Array.from(detailText.matchAll(/\d{1,3}(?:,\d{3})+\s*원|\d+\s*원/g));
    const firstPrice = priceMatches[0];
    const productName = clean(firstPrice ? detailText.slice(0, firstPrice.index).replace(/\d{1,3}%\s*$/, '') : '');
    const prices = productPriceValues(detailText);
    if (!productName) {
      previewDiagnostics.missing_title += 1;
      continue;
    }
    if (!prices.length) {
      previewDiagnostics.missing_price += 1;
      continue;
    }
    if (!imageUrl) {
      previewDiagnostics.missing_image += 1;
      continue;
    }
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
      goldbox_preview: previewDiagnostics,
    },
    sample_anchors: sampleAnchors,
    sample_images: sampleImages,
    candidates,
  };
}

function inspectFirstGoldboxCard() {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const image = document.querySelector('img[alt="product"]');
  if (!image) {
    return { ok: false, reason: 'product_image_not_found', page_url: location.href };
  }
  const card = image.parentElement?.parentElement || image.parentElement;
  const controls = Array.from(card?.querySelectorAll('button, [role="button"], a, div') || [])
    .map((node) => ({
      tag: node.tagName.toLowerCase(),
      text: clean(node.textContent).slice(0, 160),
      class_name: clean(node.className).slice(0, 180),
      role: clean(node.getAttribute('role')),
      aria_label: clean(node.getAttribute('aria-label')),
    }))
    .filter((item) => /상품정보|링크 생성/.test(item.text))
    .slice(0, 20);
  return {
    ok: true,
    page_url: location.href,
    card_text: clean(card?.textContent).slice(0, 600),
    image_src: image.currentSrc || image.src || '',
    controls,
  };
}

function inspectCoupangProductDetail() {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const absoluteUrl = (value) => {
    const raw = clean(value);
    if (!raw) return '';
    if (raw.startsWith('//')) return `https:${raw}`;
    return raw;
  };
  const priceEntries = (value) => Array.from(String(value || '').matchAll(/\d{1,3}(?:,\d{3})*\s*원|\d+\s*원/g))
    .map((match) => ({
      value: Number(match[0].replace(/[^0-9]/g, '')),
      offset: match.index || 0,
      unit_price: /(?:\(|\s)\d+(?:\.\d+)?(?:g|kg|ml|L|개|구|매|m|cm)당\s*$/i.test(String(value || '').slice(Math.max(0, (match.index || 0) - 22), match.index || 0)),
    }))
    .filter((entry) => entry.value > 0 && !entry.unit_price);
  const text = clean(document.body.innerText);
  const productId = new URL(location.href).pathname.match(/\/vp\/products\/(\d+)/)?.[1] || '';
  const factLabels = ['소비기한\\(또는 유통기한\\)', '보관방법', '개당 중량', '부위', '절단 형태', '원산지', '식품의 유형', '제조년월일', '크기', '색상', '재질', '사용대상', '장점', '제형', '총 수량', '용량', '구성'];
  const labelPattern = factLabels.join('|');
  const productFacts = factLabels.map((label) => {
    const match = text.match(new RegExp(`(${label}):\\s*(.+?)(?=\\s+(?:${labelPattern}):|\\s+쿠팡상품번호:|$)`, 'i'));
    return match ? `${match[1].replace(/\\\\/g, '')}: ${clean(match[2]).slice(0, 120)}` : '';
  }).filter(Boolean).slice(0, 4);
  const compositionMatch = text.match(/(?:개당\s*)?중량\s*×\s*수량:\s*(.+?)(?=\s+(?:적립|쿠팡캐시|쿠페이|수량빼기|소비기한|보관방법|개당 중량|쿠팡상품번호):|\s+(?:쿠폰할인|쿠폰받기|쿠폰 적용)|$)/);
  const titleCandidates = [
    document.querySelector('.prod-buy-header__title')?.textContent,
    document.querySelector('h1')?.textContent,
    document.querySelector('meta[property="og:title"]')?.getAttribute('content'),
    document.title,
  ].map(clean).filter(Boolean);
  const title = titleCandidates.find((value) => value.length > 2 && !/^쿠팡$/i.test(value)) || '';
  const titleCompositionMatch = title.match(/(?:\d+(?:\.\d+)?\s*(?:g|kg|ml|L|개|정|매|입|세트|팩|병)(?:\s*[,x×+]\s*\d+\s*(?:개|정|매|입|세트|팩|병))?)/i);
  const composition = clean(compositionMatch?.[1] || titleCompositionMatch?.[0] || '');
  const productStart = title ? text.indexOf(title) : -1;
  const productEndMarker = productStart >= 0 ? text.indexOf('쿠팡상품번호:', productStart) : -1;
  const priceScope = productStart >= 0 ? text.slice(productStart, productEndMarker >= 0 ? productEndMarker : productStart + 1800) : text.slice(0, 1800);
  const prices = priceEntries(priceScope);
  const normalPrice = prices[0]?.value || null;
  const couponIndicators = ['쿠폰할인', '쿠폰받기', '쿠폰 받기', '쿠폰 적용', '쿠폰 적용됨', '보유 쿠폰', '쿠폰가', '개인 쿠폰', '할인쿠폰', '웰컴백 쿠폰'];
  const wowIndicators = ['와우쿠폰할인가', '와우 쿠폰 할인가', '와우회원가', '와우할인', '와우 가입 시', '와우 멤버십'];
  const couponDetected = couponIndicators.some((label) => priceScope.includes(label));
  const wowConditionDetected = wowIndicators.some((label) => priceScope.includes(label));
  const personalCouponDetected = ['쿠폰받기', '쿠폰 받기', '쿠폰 적용', '쿠폰 적용됨', '보유 쿠폰', '쿠폰가', '개인 쿠폰', '할인쿠폰', '웰컴백 쿠폰'].some((label) => priceScope.includes(label));
  const pricesAfter = (label) => {
    const index = priceScope.indexOf(label);
    return index >= 0 ? prices.filter((entry) => entry.offset > index) : [];
  };
  const generalSalePrice = ['일반판매가', '일반할인가', '일반 판매가', '판매가']
    .map((label) => pricesAfter(label).slice(0, 2)[1]?.value || null)
    .find((value) => value) || prices[1]?.value || null;
  const wowPrice = wowIndicators
    .map((label) => pricesAfter(label).slice(0, 2)[1]?.value || null)
    .find((value) => value) || null;
  const couponPrice = ['쿠폰가', '쿠폰 적용가', '쿠폰 적용됨'].map((label) => pricesAfter(label)[0]?.value || null).find((value) => value) || null;
  const conditionalCandidates = [
    couponPrice ? { price: couponPrice, condition: '쿠폰 적용 시', type: personalCouponDetected ? 'personal_coupon' : 'coupon' } : null,
    wowPrice ? { price: wowPrice, condition: '와우회원 혜택 적용 시', type: 'wow_member' } : null,
  ].filter(Boolean);
  const lowestConditional = conditionalCandidates.sort((left, right) => left.price - right.price)[0] || null;
  const ogImage = absoluteUrl(document.querySelector('meta[property="og:image"]')?.getAttribute('content'));
  const thumbnailOriginalCandidate = ogImage.replace('/thumbnails/remote/492x492ex/', '/');
  const imageCandidates = [
    ...Array.from(document.querySelectorAll('.prod-image-container img, .prod-image img, img[class*="prod-image"], img[class*="product-image"]'))
      .map((image) => absoluteUrl(image.currentSrc || image.getAttribute('src') || image.getAttribute('data-src'))),
    ogImage,
    thumbnailOriginalCandidate,
  ].filter((url, index, values) => url.startsWith('https://') && values.indexOf(url) === index && !url.endsWith('.svg'));
  const sourceImageCandidate = imageCandidates.find((url) => url.includes('coupangcdn.com/') && !url.includes('/thumbnails/remote/')) || '';
  const description = productFacts.length >= 2 && composition
    ? `${productFacts.slice(0, 2).join(', ')} 정보를 확인한 ${composition} 구성 상품입니다.`
    : '';
  const features = productFacts.slice(0, 3);
  const audiences = title && composition ? [
    `${title} 구성을 찾는 분`,
    `${composition} 상품이 필요한 분`,
    '쿠폰·회원 혜택 조건을 확인할 수 있는 분',
  ] : [];
  const currentPrice = [generalSalePrice, lowestConditional?.price].filter((value) => Number.isFinite(value) && value > 0).sort((left, right) => left - right)[0] || null;
  const automaticPublishEligible = Boolean(title && productId && currentPrice && sourceImageCandidate);
  const exclusionReasons = [
    !title ? 'product_name_missing' : '',
    !productId ? 'product_id_missing' : '',
    !currentPrice ? 'current_price_unverified' : '',
    !normalPrice ? 'normal_price_unverified' : '',
    !generalSalePrice && !lowestConditional?.price ? 'sale_price_unverified' : '',
    !sourceImageCandidate ? 'source_image_unverified' : '',
  ].filter(Boolean);
  return {
    source: 'coupang-browser-product-detail',
    captured_at: new Date().toISOString(),
    product_page_url: location.href,
    product_id: productId,
    product_name: title,
    composition,
    description,
    features,
    audiences,
    source_image_url: sourceImageCandidate || ogImage,
    source_image_candidate_url: sourceImageCandidate,
    source_image_verified: false,
    normal_price: normalPrice,
    general_price: generalSalePrice,
    current_price: currentPrice,
    lowest_conditional_price: lowestConditional?.price || null,
    conditional_price_condition: lowestConditional?.condition || '',
    conditional_prices: conditionalCandidates,
    coupon_price_detected: couponDetected,
    member_price_detected: wowConditionDetected,
    personal_coupon_detected: personalCouponDetected,
    coupon_price_excluded: false,
    automatic_publish_eligible: automaticPublishEligible,
    automatic_publish_exclusion_reasons: exclusionReasons,
    publish_executed: false,
    approval_only: true,
    diagnostic: {
      title_candidates: titleCandidates.slice(0, 4),
      detected_conditions: { coupon: couponDetected, wow_or_member: wowConditionDetected, personal_coupon: personalCouponDetected },
      price_scope_sample: priceScope.slice(0, 700),
      product_facts_found: productFacts.length,
      source_image_candidate_found: Boolean(sourceImageCandidate),
      og_image_is_thumbnail: ogImage.includes('/thumbnails/remote/'),
    },
  };
}

async function generateFirstPartnerLink() {
  const clean = (value) => String(value || '').replace(/\s+/g, ' ').trim();
  const image = document.querySelector('img[alt="product"]');
  const card = image?.parentElement?.parentElement || image?.parentElement;
  const button = card?.querySelector('button.btn-generate-link') || Array.from(card?.querySelectorAll('button') || [])
    .find((node) => clean(node.textContent) === '링크 생성');
  if (!card || !button) {
    return { ok: false, reason: 'generate_link_button_not_found', page_url: location.href };
  }
  const candidate = {
    product_name: clean(card.textContent).replace(/^\d+\s*상품정보\s*링크\s*생성\s*/, '').slice(0, 400),
    preview_image_url: image.currentSrc || image.src || '',
  };
  button.click();
  await new Promise((resolve) => setTimeout(resolve, 1800));
  const bodyText = clean(document.body.innerText);
  const generatedUrls = (bodyText.match(/https:\/\/(?:link\.coupang\.com|coupa\.ng)\/[A-Za-z0-9_?=&%#./-]+/g) || [])
    .map((url) => url.replace(/[),.]+$/, ''));
  const dialogs = Array.from(document.querySelectorAll('[role="dialog"], .ant-modal, .modal, [class*="modal"]'))
    .filter((node) => clean(node.textContent))
    .map((node) => clean(node.textContent).slice(0, 1200))
    .slice(0, 3);
  return {
    ok: true,
    page_url: location.href,
    candidate,
    generated_urls: [...new Set(generatedUrls)],
    dialog_text: dialogs,
    link_detected: generatedUrls.length > 0,
  };
}

async function verifySourceImage(payload) {
  const candidate = String(payload?.source_image_candidate_url || '').trim();
  if (!candidate) return { ...payload, source_image_verified: false, source_image_verification_reason: 'non_thumbnail_source_image_not_found' };
  try {
    const response = await fetch(candidate, { cache: 'no-store', credentials: 'omit' });
    const contentType = String(response.headers.get('content-type') || '').toLowerCase();
    const blob = await response.blob();
    if (!response.ok || !contentType.startsWith('image/') || blob.size < 4096) {
      return { ...payload, source_image_verified: false, source_image_verification_reason: 'image_fetch_or_content_validation_failed' };
    }
    const bitmap = await createImageBitmap(blob);
    const width = bitmap.width;
    const height = bitmap.height;
    const verified = width >= 600 && height >= 600;
    bitmap.close();
    return {
      ...payload,
      source_image_verified: verified,
      source_image_width: width,
      source_image_height: height,
      source_image_verification_reason: verified ? '' : 'source_image_too_small',
      automatic_publish_eligible: Boolean(payload.automatic_publish_eligible && verified),
      automatic_publish_exclusion_reasons: verified ? payload.automatic_publish_exclusion_reasons : [...(payload.automatic_publish_exclusion_reasons || []), 'source_image_unverified'],
    };
  } catch (error) {
    return { ...payload, source_image_verified: false, source_image_verification_reason: 'image_fetch_failed' };
  }
}

async function storedPartnerLink(productId) {
  const stored = await chrome.storage.local.get('coupangGoldboxPartnerLinkResults');
  const results = Array.isArray(stored.coupangGoldboxPartnerLinkResults) ? stored.coupangGoldboxPartnerLinkResults : [];
  const matched = results.find((item) => String(item?.product_id || '') === String(productId || ''));
  const urls = Array.isArray(matched?.generated_urls) ? matched.generated_urls : [];
  return urls.find((url) => /^https:\/\/(?:coupa\.ng|link\.coupang\.com)\//i.test(String(url || ''))) || '';
}

function approvalCandidate(detail, affiliateUrl) {
  return {
    product_id: detail.product_id,
    product_name: detail.product_name,
    composition: detail.composition,
    product_url: detail.product_page_url,
    affiliate_url: affiliateUrl,
    original_image_url: detail.source_image_url,
    normal_price: detail.normal_price,
    sale_price: detail.general_price,
    conditional_price: detail.lowest_conditional_price,
    price_condition: detail.conditional_price_condition,
    description: detail.description,
    features: detail.features,
    audiences: detail.audiences,
    source_image_verified: detail.source_image_verified === true,
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

detailButton.addEventListener('click', async () => {
  detailButton.disabled = true;
  setStatus('현재 쿠팡 상품 상세 화면의 표시 가격과 원본 대표 이미지를 확인하는 중입니다…');
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !String(tab.url || '').startsWith('https://www.coupang.com/vp/products/')) {
      throw new Error('쿠팡 상품 상세 페이지에서만 사용할 수 있습니다.');
    }
    const results = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: inspectCoupangProductDetail });
    const detailPayload = results[0]?.result;
    const verifiedDetail = await verifySourceImage(detailPayload);
    const affiliateUrl = await storedPartnerLink(verifiedDetail?.product_id);
    const payload = {
      ...verifiedDetail,
      affiliate_url: affiliateUrl,
      approval_ready: Boolean(verifiedDetail?.automatic_publish_eligible && affiliateUrl),
      approval_exclusion_reasons: [
        ...(verifiedDetail?.automatic_publish_exclusion_reasons || []),
        !affiliateUrl ? 'partner_link_unverified' : '',
      ].filter(Boolean),
    };
    await chrome.storage.local.set({ coupangGoldboxLastVerifiedDetail: payload, coupangGoldboxLastVerifiedDetailUpdatedAt: Date.now() });
    await downloadJson(payload, `coupang-product-detail-review-${new Date().toISOString().slice(0, 10)}.json`);
    if (payload.approval_ready) {
      setStatus('일반 가격·최저 조건부 가격·원본 대표 이미지·파트너스 링크를 검증했습니다. 아래 버튼으로 텔레그램 승인 요청을 만들 수 있습니다.');
    } else {
      setStatus('가격·원본 대표 이미지·상품 사실·파트너스 링크 중 하나 이상을 검증하지 못해 승인 요청을 만들지 않았습니다. 상세 진단 JSON만 저장했습니다.');
    }
  } catch (error) {
    setStatus(`저장하지 않았습니다: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    detailButton.disabled = false;
  }
});

approvalButton.addEventListener('click', async () => {
  approvalButton.disabled = true;
  setStatus('검증된 쿠팡 상품의 텔레그램 승인 요청을 만드는 중입니다…');
  try {
    const stored = await chrome.storage.local.get(['coupangCollectorDeviceToken', 'coupangGoldboxLastVerifiedDetail']);
    const deviceToken = String(stored.coupangCollectorDeviceToken || '').trim();
    const detail = stored.coupangGoldboxLastVerifiedDetail;
    if (deviceToken.length < 24) throw new Error('쿠팡 수집기 연결 정보가 없습니다. 관리자 페이지에서 이 수집기를 한 번 연결해 주세요.');
    if (!detail?.approval_ready || !detail?.affiliate_url) throw new Error('현재 상세 검증 결과는 승인 요청 조건을 충족하지 않습니다. 상세 검증을 다시 실행해 주세요.');
    const response = await fetch(`${BLOGAUTO_ORIGIN}/api/coupang/collector/approval`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Naver-Draft-Device': deviceToken },
      body: JSON.stringify({ candidate: approvalCandidate(detail, detail.affiliate_url), ttl_minutes: 30 }),
      cache: 'no-store',
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || !body?.ok) throw new Error(body?.error || '텔레그램 승인 요청을 만들지 못했습니다.');
    await chrome.storage.local.remove('coupangGoldboxLastVerifiedDetail');
    setStatus('텔레그램 승인 요청을 보냈습니다. 승인 전에는 네이버 발행을 실행하지 않습니다.');
  } catch (error) {
    setStatus(`승인 요청을 만들지 않았습니다: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    approvalButton.disabled = false;
  }
});

batchButton.addEventListener('click', async () => {
  batchButton.disabled = true;
  setStatus('정제 가능한 골드박스 후보의 파트너스 링크를 순차 생성하는 중입니다…');
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !String(tab.url || '').startsWith('https://partners.coupang.com/')) {
      throw new Error('쿠팡 파트너스 골드박스 탭에서만 사용할 수 있습니다.');
    }
    const response = await chrome.runtime.sendMessage({ type: 'START_GOLDBOX_LINK_BATCH', tabId: tab.id });
    if (!response?.ok) {
      throw new Error(response?.error || '일괄 링크 생성을 시작하지 못했습니다.');
    }
    setStatus(`${response.summary.success}건 링크 결과를 저장했습니다. 실패 ${response.summary.failed}건은 결과 JSON에서 확인합니다. 네이버 발행은 실행하지 않았습니다.`);
  } catch (error) {
    setStatus(`저장하지 않았습니다: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    batchButton.disabled = false;
  }
});

generateButton.addEventListener('click', async () => {
  generateButton.disabled = true;
  setStatus('첫 후보의 쿠팡 파트너스 링크를 생성하고 결과만 저장하는 중입니다…');
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !String(tab.url || '').startsWith('https://partners.coupang.com/')) {
      throw new Error('쿠팡 파트너스 골드박스 탭에서만 사용할 수 있습니다.');
    }
    const results = await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, func: generateFirstPartnerLink });
    const payload = {
      source: 'coupang-partners-goldbox-link-generation',
      captured_at: new Date().toISOString(),
      page_url: tab.url,
      publish_executed: false,
      frames: results.map((result) => ({ frame_id: result.frameId, result: result.result || {} })),
    };
    await downloadJson(payload, `coupang-goldbox-link-result-${new Date().toISOString().slice(0, 10)}.json`);
    const succeeded = results.some((result) => result.result?.link_detected);
    setStatus(succeeded ? '제휴 링크 결과 JSON을 저장했습니다. 네이버 발행은 실행하지 않았습니다.' : '링크 생성 결과 진단 JSON을 저장했습니다. 링크가 표시되는 위치를 확인하겠습니다.');
  } catch (error) {
    setStatus(`저장하지 않았습니다: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    generateButton.disabled = false;
  }
});

inspectButton.addEventListener('click', async () => {
  inspectButton.disabled = true;
  setStatus('첫 후보 카드의 상품정보 제어 구조를 확인하는 중입니다…');
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !String(tab.url || '').startsWith('https://partners.coupang.com/')) {
      throw new Error('쿠팡 파트너스 골드박스 탭에서만 사용할 수 있습니다.');
    }
    const results = await chrome.scripting.executeScript({ target: { tabId: tab.id, allFrames: true }, func: inspectFirstGoldboxCard });
    const payload = {
      source: 'coupang-partners-goldbox-product-info-diagnostic',
      captured_at: new Date().toISOString(),
      page_url: tab.url,
      frames: results.map((result) => ({ frame_id: result.frameId, result: result.result || {} })),
    };
    await downloadJson(payload, `coupang-goldbox-product-info-diagnostic-${new Date().toISOString().slice(0, 10)}.json`);
    setStatus('상품정보 제어 구조 진단 JSON을 저장했습니다. 링크 생성·발행은 실행하지 않았습니다.');
  } catch (error) {
    setStatus(`저장하지 않았습니다: ${error instanceof Error ? error.message : String(error)}`);
  } finally {
    inspectButton.disabled = false;
  }
});

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
