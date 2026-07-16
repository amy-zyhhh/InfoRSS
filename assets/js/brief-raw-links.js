(function () {
  const article = document.querySelector(".brief-page .prose");
  if (!article) return;

  function siteUrl(value) {
    const raw = String(value || "");
    if (!raw || /^https?:\/\//i.test(raw)) return raw;
    const base = String(window.INFO_RSS_BASE_URL || "/").replace(/\/+$/, "");
    return `${base}/${raw.replace(/^\/+/, "")}`;
  }

  function basePath() {
    return String(window.INFO_RSS_BASE_URL || "/").replace(/\/+$/, "");
  }

  function stripBasePath(value) {
    let path = String(value || "").replace(/\/+$/, "/");
    try {
      path = new URL(path, window.location.origin).pathname.replace(/\/+$/, "/");
    } catch {}

    const base = basePath();
    if (base && base !== "/" && path.startsWith(`${base}/`)) {
      path = path.slice(base.length).replace(/\/+$/, "/");
    }
    return path || "/";
  }

  function normalizeUrl(value) {
    try {
      return new URL(value, window.location.origin).href;
    } catch {
      return String(value || "");
    }
  }

  function currentBriefPath() {
    if (window.INFO_RSS_CURRENT_BRIEF_URL) {
      return stripBasePath(window.INFO_RSS_CURRENT_BRIEF_URL);
    }
    const pathname = window.location.pathname.replace(/\/+$/, "/");
    const base = basePath();
    if (base && base !== "/" && pathname.startsWith(`${base}/`)) {
      return pathname.slice(base.length).replace(/\/+$/, "/");
    }
    return pathname.replace(/\/+$/, "/");
  }

  function addRawLinks(items) {
    const path = currentBriefPath();
    const bySource = new Map();
    items
      .filter((item) => stripBasePath(item.page_url || "") === path)
      .forEach((item) => {
        bySource.set(normalizeUrl(item.source_url), item.raw_url);
      });

    article.querySelectorAll("h3 > a[href]").forEach((link) => {
      const rawUrl = bySource.get(normalizeUrl(link.getAttribute("href"))) || bySource.get(normalizeUrl(link.href));
      if (!rawUrl || link.closest("h3").nextElementSibling?.classList.contains("raw-link")) return;

      const row = document.createElement("p");
      row.className = "raw-link";
      const rawLink = document.createElement("a");
      rawLink.href = siteUrl(rawUrl);
      rawLink.textContent = "已抓取的原文";
      row.appendChild(rawLink);
      link.closest("h3").insertAdjacentElement("afterend", row);
    });
  }

  fetch(window.INFO_RSS_SEARCH_INDEX || "/assets/search-index.json")
    .then((response) => {
      if (!response.ok) throw new Error("search index not found");
      return response.json();
    })
    .then(addRawLinks)
    .catch(() => {});
})();
