(() => {
  const loginPanel = document.querySelector("#loginPanel");
  const loginForm = document.querySelector("#loginForm");
  const password = document.querySelector("#password");
  const loginStatus = document.querySelector("#loginStatus");
  const dashboard = document.querySelector("#dashboard");
  const logout = document.querySelector("#logout");
  const source = document.querySelector("#source");
  const size = document.querySelector("#size");
  const loadProducts = document.querySelector("#loadProducts");
  const collectProducts = document.querySelector("#collectProducts");
  const collectionStatus = document.querySelector("#collectionStatus");
  const productRows = document.querySelector("#productRows");
  const productCount = document.querySelector("#productCount");

  let csrfToken = "";

  const setStatus = (element, text, tone = "") => {
    element.textContent = text;
    element.className = `status ${tone}`.trim();
  };

  const setBusy = (busy) => {
    loadProducts.disabled = busy;
    collectProducts.disabled = busy;
    logout.disabled = busy;
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

  const formatPrice = (value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? `${parsed.toLocaleString("ko-KR")}원` : "—";
  };

  const formatDate = (value) => {
    if (!value) return "—";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "—" : date.toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" });
  };

  const textCell = (value) => {
    const cell = document.createElement("td");
    cell.textContent = value;
    return cell;
  };

  const badge = (text, tone) => {
    const result = document.createElement("span");
    result.className = `badge ${tone}`;
    result.textContent = text;
    return result;
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

  const enterDashboard = () => {
    loginPanel.hidden = true;
    dashboard.hidden = false;
    password.value = "";
    setStatus(loginStatus, "");
  };

  const leaveDashboard = (message = "로그인 후 수집 목록을 확인할 수 있습니다.") => {
    csrfToken = "";
    dashboard.hidden = true;
    loginPanel.hidden = false;
    clearRows("로그인 후 수집 목록을 불러오세요.");
    setStatus(loginStatus, message);
  };

  const api = async (path, options = {}) => {
    const headers = { ...(options.headers || {}) };
    if (options.method && options.method !== "GET") {
      headers["Content-Type"] = "application/json";
      headers["X-CSRF-Token"] = csrfToken;
    }
    const response = await fetch(path, {
      ...options,
      headers,
      credentials: "same-origin",
      cache: "no-store",
    });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401) {
      leaveDashboard("세션이 만료됐습니다. 다시 로그인해 주세요.");
      throw new Error("세션이 만료됐습니다.");
    }
    if (!response.ok || !payload.ok) {
      throw new Error(payload.error || "관리자 요청을 처리하지 못했습니다.");
    }
    return payload.result;
  };

  const currentSize = () => {
    const maximum = source.value === "today-deals" ? 30 : 100;
    const value = Math.max(1, Math.min(maximum, Number(size.value) || 30));
    size.value = String(value);
    return value;
  };

  const load = async (quiet = false) => {
    setBusy(true);
    if (!quiet) setStatus(collectionStatus, "저장된 수집 목록을 불러오는 중입니다.");
    try {
      const items = await api(`/api/admin/toss/products?source=${encodeURIComponent(source.value)}&limit=${currentSize()}`);
      renderRows(Array.isArray(items) ? items : []);
      setStatus(collectionStatus, `${Array.isArray(items) ? items.length : 0}건의 저장 목록을 불러왔습니다.`, "success");
    } catch (error) {
      if (dashboard.hidden) return;
      clearRows("목록을 불러오지 못했습니다.");
      setStatus(collectionStatus, error.message || "목록 조회 중 오류가 발생했습니다.", "error");
    } finally {
      setBusy(false);
    }
  };

  const collect = async () => {
    setBusy(true);
    setStatus(collectionStatus, "토스 Open API에서 상품 목록을 수집하고 있습니다. 잠시만 기다려 주세요.");
    try {
      const result = await api("/api/admin/toss/collect", {
        method: "POST",
        body: JSON.stringify({ source: source.value, size: currentSize() }),
      });
      setStatus(collectionStatus, `${result.saved_count || 0}건을 저장했습니다. 수집 목록을 새로고침합니다.`, "success");
      await load(true);
    } catch (error) {
      if (!dashboard.hidden) setStatus(collectionStatus, error.message || "토스 수집 중 오류가 발생했습니다.", "error");
    } finally {
      setBusy(false);
    }
  };

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = password.value;
    if (!value) return;
    const submit = loginForm.querySelector("button[type=submit]");
    submit.disabled = true;
    setStatus(loginStatus, "로그인 중입니다.");
    try {
      const response = await fetch("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ password: value }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok || !payload.result?.csrf_token) {
        throw new Error(payload.error || "로그인에 실패했습니다.");
      }
      csrfToken = payload.result.csrf_token;
      enterDashboard();
      await load();
    } catch (error) {
      password.value = "";
      setStatus(loginStatus, error.message === "too_many_attempts" ? "로그인 시도가 잠시 제한됐습니다. 나중에 다시 시도해 주세요." : "비밀번호를 확인해 주세요.", "error");
    } finally {
      submit.disabled = false;
    }
  });

  logout.addEventListener("click", async () => {
    setBusy(true);
    try {
      await api("/api/admin/logout", { method: "POST", body: "{}" });
    } catch (_) {
      // The server may have already expired the session; clear the browser view either way.
    } finally {
      leaveDashboard("로그아웃했습니다.");
      setBusy(false);
    }
  });

  loadProducts.addEventListener("click", () => load());
  collectProducts.addEventListener("click", collect);
  source.addEventListener("change", () => {
    size.max = source.value === "today-deals" ? "30" : "100";
    currentSize();
    load();
  });

  (async () => {
    try {
      const session = await api("/api/admin/session");
      csrfToken = session.csrf_token || "";
      if (!csrfToken) throw new Error("세션 정보가 없습니다.");
      enterDashboard();
      await load();
    } catch (_) {
      leaveDashboard();
    }
  })();
})();
