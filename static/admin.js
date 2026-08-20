(() => {
  const loginPanel = document.querySelector("#loginPanel");
  const loginForm = document.querySelector("#loginForm");
  const password = document.querySelector("#password");
  const loginStatus = document.querySelector("#loginStatus");
  const dashboard = document.querySelector("#dashboard");
  const logout = document.querySelector("#logout");
  const publisherForm = document.querySelector("#publisherForm");
  const publisherId = document.querySelector("#publisherId");
  const publisherStatus = document.querySelector("#publisherStatus");
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
    publisherForm.querySelector("button[type=submit]").disabled = busy;
    productRows.querySelectorAll("button[data-issue-id], button[data-copy-url], button[data-prepare-draft]").forEach((button) => {
      button.disabled = busy;
    });
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
      if (item.short_url) {
        linkCell.append(badge("발급됨", "ok"));
        const copyButton = document.createElement("button");
        copyButton.type = "button";
        copyButton.className = "secondary mini-action";
        copyButton.dataset.copyUrl = item.short_url;
        copyButton.textContent = "복사";
        linkCell.append(copyButton);
        const draftButton = document.createElement("button");
        draftButton.type = "button";
        draftButton.className = "primary mini-action";
        draftButton.dataset.prepareDraft = item.taca_item_id || "";
        draftButton.disabled = Boolean(item.is_sold_out) || !item.taca_item_id;
        draftButton.textContent = item.is_sold_out ? "품절" : "네이버 입력";
        linkCell.append(draftButton);
      } else {
        const issueButton = document.createElement("button");
        issueButton.type = "button";
        issueButton.className = "primary mini-action";
        issueButton.dataset.issueId = item.taca_item_id || "";
        issueButton.disabled = Boolean(item.is_sold_out) || !item.taca_item_id;
        issueButton.textContent = item.is_sold_out ? "품절" : "링크 발급";
        linkCell.append(issueButton);
      }
      row.append(linkCell);
      productRows.append(row);
    }
  };

  const enterDashboard = () => {
    // Set both the semantic hidden state and inline display so cached layout CSS cannot leave both panels visible.
    loginPanel.hidden = true;
    loginPanel.style.display = "none";
    dashboard.hidden = false;
    dashboard.style.display = "block";
    password.value = "";
    setStatus(loginStatus, "");
  };

  const leaveDashboard = (message = "로그인 후 수집 목록을 확인할 수 있습니다.") => {
    csrfToken = "";
    dashboard.hidden = true;
    dashboard.style.display = "none";
    loginPanel.hidden = false;
    loginPanel.style.display = "grid";
    clearRows("로그인 후 수집 목록을 불러오세요.");
    setStatus(loginStatus, message);
  };

  const EXTENSION_REQUEST_ATTR = "data-naver-draft-assistant-request";
  const EXTENSION_RESPONSE_ATTR = "data-naver-draft-assistant-response";

  const requestExtension = (request) => new Promise((resolve) => {
    const requestId = crypto.randomUUID();
    const timeout = setTimeout(() => {
      observer.disconnect();
      resolve({ ok: false, error: "확장 프로그램이 응답하지 않았습니다. 확장 프로그램과 이 페이지를 새로고침해 주세요." });
    }, 3000);
    const observer = new MutationObserver(() => {
      try {
        const response = JSON.parse(document.documentElement.getAttribute(EXTENSION_RESPONSE_ATTR) || "{}");
        if (response.requestId !== requestId) return;
        clearTimeout(timeout);
        observer.disconnect();
        resolve(response);
      } catch {
        // Wait for a complete extension response.
      }
    });
    observer.observe(document.documentElement, { attributes: true, attributeFilter: [EXTENSION_RESPONSE_ATTR] });
    document.documentElement.setAttribute(EXTENSION_REQUEST_ATTR, JSON.stringify({ ...request, requestId }));
  });

  const storeDraftInExtension = (draft) => requestExtension({ type: "STORE_DRAFT", draft });

  const pairExtensionDevice = async () => {
    const result = await api("/api/admin/extension/pair", { method: "POST", body: "{}" });
    const response = await requestExtension({ type: "PAIR_DEVICE", deviceToken: result.device_token || "" });
    if (!response.ok) throw new Error(response.error || "확장 프로그램 연결에 실패했습니다.");
  };

  const showApprovalDispatchTrace = async () => {
    const response = await requestExtension({ type: "GET_APPROVAL_TRACE" });
    if (!response.ok || !response.trace) return;
    const trace = response.trace;
    if (trace.step === "dispatch_failed" && trace.error) {
      setStatus(collectionStatus, `승인된 초안 자동 입력이 중단됐습니다: ${trace.error}`, "error");
    }
  };

  const copyOriginalImage = async (imageUrl) => {
    if (!navigator.clipboard?.write || typeof ClipboardItem === "undefined") {
      throw new Error("Chrome에서 원본 이미지 클립보드 준비 기능을 사용할 수 없습니다.");
    }
    const response = await fetch(imageUrl, { credentials: "same-origin", cache: "no-store" });
    if (!response.ok) throw new Error("원본 대표 이미지를 불러오지 못했습니다.");
    const blob = await response.blob();
    if (!blob.type.startsWith("image/")) throw new Error("원본 대표 이미지 형식을 확인하지 못했습니다.");
    await navigator.clipboard.write([new ClipboardItem({ [blob.type]: blob })]);
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

  const loadSettings = async () => {
    const settings = await api("/api/admin/settings");
    const configured = Boolean(settings.publisher_configured);
    publisherForm.hidden = configured;
    publisherForm.style.display = configured ? "none" : "";
    if (settings.publisher_source === "environment") {
      setStatus(publisherStatus, "환경 변수 TOSS_OPEN_API_PUBLISHER_ID가 적용 중입니다. 퍼블리셔 UUID는 화면에 표시하지 않으며, 선택한 상품의 쉐어링크를 발급할 수 있습니다.", "success");
    } else if (settings.publisher_source === "database") {
      setStatus(publisherStatus, "퍼블리셔 UUID가 서버 설정에 저장되어 있습니다. UUID는 화면에 표시하지 않으며, 선택한 상품의 쉐어링크를 발급할 수 있습니다.", "success");
    } else {
      publisherId.placeholder = "토스에서 안내받은 퍼블리셔 UUID 입력";
      setStatus(publisherStatus, "권장: TOSS_OPEN_API_PUBLISHER_ID 환경 변수에 UUID를 설정하세요. 환경 변수 설정 전에는 이 화면에서만 보조값을 저장할 수 있습니다.");
    }
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
      const auto = result.auto_issuance || {};
      const autoSummary = auto.enabled
        ? ` 신규 발급 ${Number(auto.issued) || 0}건, 기존 링크 재사용 ${Number(auto.reused) || 0}건입니다.`
        : " 자동 링크 발급은 현재 꺼져 있습니다.";
      const skipped = (Number(auto.skipped_sold_out) || 0) + (Number(auto.skipped_invalid) || 0);
      const suffix = [
        skipped ? `품절·유효하지 않은 항목 ${skipped}건은 제외했습니다.` : "",
        auto.quota_exceeded ? "일일 새 링크 발급 한도에 도달해 남은 항목은 건너뛰었습니다." : "",
        Number(auto.failed) ? `발급 실패 ${Number(auto.failed)}건이 있습니다.` : "",
      ].filter(Boolean).join(" ");
      setStatus(
        collectionStatus,
        `${result.saved_count || 0}건을 저장했습니다.${autoSummary}${suffix ? ` ${suffix}` : ""} 수집 목록을 새로고침합니다.`,
        Number(auto.failed) || auto.quota_exceeded ? "error" : "success",
      );
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
      await loadSettings();
      await pairExtensionDevice().catch(() => undefined);
      setTimeout(() => { showApprovalDispatchTrace().catch(() => undefined); }, 1500);
      await load();
    } catch (error) {
      password.value = "";
      setStatus(loginStatus, error.message === "too_many_attempts" ? "로그인 시도가 잠시 제한됐습니다. 나중에 다시 시도해 주세요." : "비밀번호를 확인해 주세요.", "error");
    } finally {
      submit.disabled = false;
    }
  });

  publisherForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const value = publisherId.value.trim();
    if (!value) {
      setStatus(publisherStatus, "환경 변수를 쓰는 경우 이 입력칸을 비워 두어도 됩니다. DB 보조값을 저장하려면 UUID를 입력해 주세요.", "error");
      return;
    }
    setBusy(true);
    try {
      await api("/api/admin/settings/publisher", {
        method: "POST",
        body: JSON.stringify({ publisher_id: value }),
      });
      publisherId.value = "";
      await loadSettings();
    } catch (error) {
      setStatus(publisherStatus, error.message || "퍼블리셔 UUID를 저장하지 못했습니다.", "error");
    } finally {
      setBusy(false);
    }
  });

  productRows.addEventListener("click", async (event) => {
    const target = event.target instanceof Element ? event.target.closest("button") : null;
    if (!target) return;
    const draftItemId = target.dataset.prepareDraft;
    if (draftItemId) {
      const writerTab = window.open("about:blank", "_blank");
      if (!writerTab) {
        setStatus(collectionStatus, "Chrome에서 새 탭 열기를 허용한 뒤 다시 시도해 주세요.", "error");
        return;
      }
      setBusy(true);
      setStatus(collectionStatus, "상품·가격·원본 이미지·쉐어링크·중복 여부를 다시 확인하고 네이버 초안을 준비합니다.");
      try {
        const result = await api("/api/admin/toss/drafts", {
          method: "POST",
          body: JSON.stringify({ taca_item_id: draftItemId }),
        });
        await copyOriginalImage(result.draft?.imageUrl || "");
        const extension = await storeDraftInExtension(result.draft || {});
        if (!extension.ok) throw new Error(extension.error || "확장 프로그램에 초안을 전달하지 못했습니다.");
        writerTab.location.replace(result.naver_write_url || "https://blog.naver.com/GoBlogWrite.naver?categoryNo=39");
        setStatus(collectionStatus, `‘${result.product_name || "선택 상품"}’ 1건을 네이버 글쓰기 화면에 입력합니다. 발행은 자동으로 수행하지 않습니다.`, "success");
      } catch (error) {
        writerTab.close();
        setStatus(collectionStatus, error.message || "네이버 초안 준비 중 오류가 발생했습니다.", "error");
      } finally {
        setBusy(false);
      }
      return;
    }
    const copyUrl = target.dataset.copyUrl;
    if (copyUrl) {
      try {
        await navigator.clipboard.writeText(copyUrl);
        setStatus(collectionStatus, "쉐어링크를 클립보드에 복사했습니다.", "success");
      } catch (_) {
        setStatus(collectionStatus, "브라우저가 클립보드 복사를 허용하지 않았습니다. 링크를 직접 복사해 주세요.", "error");
      }
      return;
    }
    const itemId = target.dataset.issueId;
    if (!itemId) return;
    target.disabled = true;
    target.textContent = "발급 중";
    setStatus(collectionStatus, "선택한 상품의 토스 쉐어링크를 발급하고 있습니다.");
    try {
      const result = await api("/api/admin/toss/links", {
        method: "POST",
        body: JSON.stringify({ taca_item_id: itemId }),
      });
      setStatus(collectionStatus, result.reused ? "기존 쉐어링크를 다시 불러왔습니다." : "쉐어링크를 발급해 저장했습니다.", "success");
      await load(true);
    } catch (error) {
      target.disabled = false;
      target.textContent = "링크 발급";
      setStatus(collectionStatus, error.message || "쉐어링크를 발급하지 못했습니다.", "error");
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
      await loadSettings();
      await pairExtensionDevice().catch(() => undefined);
      setTimeout(() => { showApprovalDispatchTrace().catch(() => undefined); }, 1500);
      await load();
    } catch (_) {
      leaveDashboard();
    }
  })();
})();
