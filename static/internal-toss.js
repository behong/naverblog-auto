(() => {
  const TOKEN_KEY = "naverblog-auto.internal-toss.access-token";
  const accessForm = document.querySelector("#accessForm");
  const accessToken = document.querySelector("#accessToken");
  const clearToken = document.querySelector("#clearToken");
  const accessStatus = document.querySelector("#accessStatus");
  const source = document.querySelector("#source");
  const size = document.querySelector("#size");
  const loadProducts = document.querySelector("#loadProducts");
  const collectProducts = document.querySelector("#collectProducts");
  const collectionStatus = document.querySelector("#collectionStatus");
  const productRows = document.querySelector("#productRows");
  const productCount = document.querySelector("#productCount");

  let token = sessionStorage.getItem(TOKEN_KEY) || "";
  accessToken.value = token;

  const formatPrice = (value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? `${parsed.toLocaleString("ko-KR")}원` : "—";
  };

  const formatDate = (value) => {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" });
  };

  const setStatus = (element, text, tone = "") => {
    element.textContent = text;
    element.className = `status ${tone}`.trim();
  };

  const setBusy = (busy) => {
    loadProducts.disabled = busy;
    collectProducts.disabled = busy;
  };

  const bearerHeaders = () => ({
    "Authorization": `Bearer ${token}`,
    "Content-Type": "application/json",
  });

  const requireToken = () => {
    if (token) return true;
    setStatus(accessStatus, "접근 토큰을 입력한 뒤 연결해 주세요.", "error");
    accessToken.focus();
    return false;
  };

  const clearRows = (message) => {
    productRows.replaceChildren();
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 7;
    cell.className = "empty";
    cell.textContent = message;
    row.append(cell);
    productRows.append(row);
    productCount.textContent = "0건";
  };

  const badge = (text, tone) => {
    const result = document.createElement("span");
    result.className = `badge ${tone}`;
    result.textContent = text;
    return result;
  };

  const textCell = (value) => {
    const cell = document.createElement("td");
    cell.textContent = value;
    return cell;
  };

  const renderRows = (items) => {
    productRows.replaceChildren();
    productCount.textContent = `${items.length}건`;
    if (!items.length) {
      clearRows("저장된 수집 데이터가 없습니다. ‘토스에서 새로 수집’을 눌러 시작하세요.");
      return;
    }
    for (const item of items) {
      const row = document.createElement("tr");
      row.append(textCell(item.rank ? `${item.rank}위` : "—"));

      const productCell = document.createElement("td");
      const product = document.createElement("div");
      product.className = "product";
      if (item.thumbnail_url) {
        const image = document.createElement("img");
        image.src = `/api/image?url=${encodeURIComponent(item.thumbnail_url)}`;
        image.alt = "";
        image.loading = "lazy";
        product.append(image);
      }
      const details = document.createElement("div");
      const name = document.createElement("div");
      name.className = "product-name";
      name.title = item.product_name || "";
      name.textContent = item.product_name || "상품명 없음";
      const id = document.createElement("div");
      id.className = "product-id";
      id.textContent = `옵션 ID ${item.taca_item_id || "—"}`;
      details.append(name, id);
      product.append(details);
      productCell.append(product);
      row.append(productCell);

      row.append(textCell(formatPrice(item.display_price)));
      row.append(textCell(item.discount_rate == null ? "—" : `${item.discount_rate}%`));
      const stateCell = document.createElement("td");
      stateCell.append(item.is_sold_out ? badge("품절", "alert") : badge("판매중", "ok"));
      row.append(stateCell);
      row.append(textCell(formatDate(item.today_deal_end_at)));
      const linkCell = document.createElement("td");
      linkCell.append(item.short_url ? badge("발급됨", "ok") : badge("미발급", "muted"));
      row.append(linkCell);
      productRows.append(row);
    }
  };

  const handleUnauthorized = () => {
    token = "";
    sessionStorage.removeItem(TOKEN_KEY);
    accessToken.value = "";
    setStatus(accessStatus, "접근 토큰을 다시 확인해 주세요.", "error");
  };

  const api = async (path, options = {}) => {
    const response = await fetch(path, {
      ...options,
      headers: { ...bearerHeaders(), ...(options.headers || {}) },
      cache: "no-store",
    });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401) {
      handleUnauthorized();
      throw new Error("접근 권한이 없습니다.");
    }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "내부 요청을 처리하지 못했습니다.");
    }
    return payload.result;
  };

  const currentSource = () => source.value;
  const currentSize = () => {
    const maximum = currentSource() === "today-deals" ? 30 : 100;
    const value = Math.max(1, Math.min(maximum, Number(size.value) || 30));
    size.value = String(value);
    return value;
  };

  const load = async (quiet = false) => {
    if (!requireToken()) return;
    setBusy(true);
    if (!quiet) setStatus(collectionStatus, "저장된 수집 목록을 불러오는 중입니다.");
    try {
      const items = await api(`/api/automation/toss/products?source=${encodeURIComponent(currentSource())}&limit=${currentSize()}`);
      renderRows(Array.isArray(items) ? items : []);
      setStatus(collectionStatus, `${Array.isArray(items) ? items.length : 0}건의 저장 목록을 불러왔습니다.`, "success");
    } catch (error) {
      clearRows("목록을 불러오지 못했습니다.");
      setStatus(collectionStatus, error.message || "목록 조회 중 오류가 발생했습니다.", "error");
    } finally {
      setBusy(false);
    }
  };

  const collect = async () => {
    if (!requireToken()) return;
    const count = currentSize();
    setBusy(true);
    setStatus(collectionStatus, "토스 Open API에서 상품 목록을 수집하고 있습니다. 잠시만 기다려 주세요.");
    try {
      const result = await api("/api/automation/toss/collect", {
        method: "POST",
        body: JSON.stringify({ source: currentSource(), size: count }),
      });
      setStatus(collectionStatus, `${result.saved_count || 0}건을 저장했습니다. 수집 목록을 새로고침합니다.`, "success");
      await load(true);
    } catch (error) {
      setStatus(collectionStatus, error.message || "토스 수집 중 오류가 발생했습니다.", "error");
      setBusy(false);
    }
  };

  accessForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const value = accessToken.value.trim();
    if (!value) {
      setStatus(accessStatus, "접근 토큰을 입력해 주세요.", "error");
      return;
    }
    token = value;
    sessionStorage.setItem(TOKEN_KEY, token);
    setStatus(accessStatus, "이 브라우저 탭 세션에만 접근 토큰을 보관합니다.", "success");
    load();
  });

  clearToken.addEventListener("click", () => {
    token = "";
    sessionStorage.removeItem(TOKEN_KEY);
    accessToken.value = "";
    clearRows("접근 토큰을 입력하면 내부 수집 목록을 볼 수 있습니다.");
    setStatus(accessStatus, "탭 세션의 접근 토큰을 지웠습니다.");
    setStatus(collectionStatus, "연결 후 저장된 수집 목록을 불러오세요.");
  });

  loadProducts.addEventListener("click", () => load());
  collectProducts.addEventListener("click", collect);
  source.addEventListener("change", () => {
    size.max = source.value === "today-deals" ? "30" : "100";
    currentSize();
    if (token) load();
  });

  if (token) {
    setStatus(accessStatus, "이 브라우저 탭 세션에 연결된 접근 토큰이 있습니다.", "success");
    load();
  }
})();
