(() => {
  const TOKEN_KEY = "naverblog-auto.admin-setup.access-token";
  const form = document.querySelector("#setupForm");
  const accessToken = document.querySelector("#accessToken");
  const newPassword = document.querySelector("#newPassword");
  const confirmation = document.querySelector("#confirmation");
  const status = document.querySelector("#setupStatus");
  const submit = form.querySelector("button[type=submit]");

  accessToken.value = sessionStorage.getItem(TOKEN_KEY) || "";

  const setStatus = (text, tone = "") => {
    status.textContent = text;
    status.className = `status ${tone}`.trim();
  };

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const token = accessToken.value.trim();
    const password = newPassword.value;
    const repeated = confirmation.value;
    if (!token) {
      setStatus("기존 내부 접근 토큰을 입력해 주세요.", "error");
      return;
    }
    if (password.length < 12) {
      setStatus("새 관리자 비밀번호는 12자 이상으로 설정해 주세요.", "error");
      return;
    }
    if (password !== repeated) {
      setStatus("새 관리자 비밀번호 확인이 일치하지 않습니다.", "error");
      return;
    }

    sessionStorage.setItem(TOKEN_KEY, token);
    submit.disabled = true;
    setStatus("관리자 비밀번호를 안전하게 설정하고 있습니다.");
    try {
      const response = await fetch("/api/admin/setup", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${token}`,
          "Content-Type": "application/json",
        },
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify({ password, confirmation: repeated }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok || !payload.ok) {
        throw new Error(payload.error || "관리자 비밀번호를 설정하지 못했습니다.");
      }
      sessionStorage.removeItem(TOKEN_KEY);
      accessToken.value = "";
      newPassword.value = "";
      confirmation.value = "";
      setStatus("설정이 완료됐습니다. 이제 /admin/에서 새 비밀번호로 로그인해 주세요.", "success");
      const link = document.createElement("a");
      link.href = "/admin/";
      link.textContent = "관리자 로그인으로 이동";
      link.style.display = "inline-block";
      link.style.marginTop = "10px";
      link.style.color = "#0064ff";
      link.style.fontWeight = "800";
      status.after(link);
    } catch (error) {
      setStatus(error.message || "설정 중 오류가 발생했습니다.", "error");
    } finally {
      submit.disabled = false;
    }
  });
})();
