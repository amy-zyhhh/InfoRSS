(function () {
  const state = {
    items: [],
    query: "",
    category: "",
    audience: "",
    start: "",
    end: "",
    fullText: false,
    rawTexts: {},
    rawLoading: null,
  };

  const els = {
    query: document.getElementById("search-input"),
    category: document.getElementById("category-filter"),
    fullText: document.getElementById("fulltext-filter"),
    audience: document.getElementById("audience-filter"),
    start: document.getElementById("date-start"),
    end: document.getElementById("date-end"),
    reset: document.getElementById("reset-filters"),
    results: document.getElementById("search-results"),
    count: document.getElementById("result-count"),
  };

  if (!els.query || !els.results || !els.count) {
    return;
  }

  function itemDate(item) {
    return (item.published_at || "").slice(0, 10);
  }

  function normalize(value) {
    return String(value || "").toLowerCase().trim();
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function siteUrl(value) {
    const raw = String(value || "");
    if (!raw || /^https?:\/\//i.test(raw)) return raw;
    const base = String(window.INFO_RSS_BASE_URL || "/").replace(/\/+$/, "");
    return `${base}/${raw.replace(/^\/+/, "")}`;
  }

  function itemRawText(item) {
    return state.rawTexts[item.id] || "";
  }

  function loadRawIndex() {
    if (!state.fullText) return Promise.resolve();
    if (Object.keys(state.rawTexts).length) return Promise.resolve();
    if (state.rawLoading) return state.rawLoading;

    const first = state.items.find((item) => item.raw_index_url);
    if (!first) return Promise.resolve();

    state.rawLoading = fetch(siteUrl(first.raw_index_url))
      .then((response) => {
        if (!response.ok) throw new Error("raw search index not found");
        return response.json();
      })
      .then((rawTexts) => {
        state.rawTexts = rawTexts || {};
      })
      .catch(() => {
        state.rawTexts = {};
      })
      .finally(() => {
        state.rawLoading = null;
      });
    return state.rawLoading;
  }

  function uniqueValues(key) {
    return Array.from(new Set(state.items.map((item) => item[key]).filter(Boolean))).sort((a, b) =>
      a.localeCompare(b, "zh-Hans-CN")
    );
  }

  function fillSelect(select, values, firstLabel) {
    select.innerHTML = `<option value="">${firstLabel}</option>`;
    values.forEach((value) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = value;
      select.appendChild(option);
    });
  }

  function matches(item) {
    const haystack = normalize(state.fullText ? `${item.text || ""} ${itemRawText(item)}` : item.text);
    const query = normalize(state.query);
    const date = itemDate(item);

    if (query && !haystack.includes(query)) return false;
    if (state.category && item.category !== state.category) return false;
    if (state.audience && item.audience !== state.audience) return false;
    if (state.start && date && date < state.start) return false;
    if (state.end && date && date > state.end) return false;
    return true;
  }

  function render(items) {
    els.count.textContent = `${items.length} 条结果`;
    if (!items.length) {
      els.results.innerHTML = '<p class="empty">没有匹配的通知。</p>';
      return;
    }

    els.results.innerHTML = items
      .map((item) => {
        const keywords = item.keywords
          ? item.keywords
              .split(/[，,、]/)
              .map((keyword) => `<span>${escapeHtml(keyword.trim())}</span>`)
              .join("")
          : "";
        const query = normalize(state.query);
        const textHit = query && normalize(item.text).includes(query);
        const rawHit = state.fullText && query && !textHit && normalize(itemRawText(item)).includes(query);
        return `
          <article class="notice-card">
            <div class="notice-meta">
              <span>${escapeHtml(item.category)}</span>
              <time>${escapeHtml(item.published_at)}</time>
            </div>
            <h3><a href="${escapeHtml(item.source_url || item.page_url)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a></h3>
            <p>${escapeHtml(item.summary)}</p>
            <div class="notice-detail">
              <span>适用对象：${escapeHtml(item.audience || "未标注")}</span>
              ${
                item.raw_url
                  ? `<span class="notice-actions"><a href="${escapeHtml(siteUrl(item.raw_url))}">已抓取的原文</a></span>`
                  : ""
              }
            </div>
            ${rawHit ? '<div class="hit-note">命中：已抓取原文</div>' : ""}
            <div class="tag-list">${keywords}</div>
          </article>
        `;
      })
      .join("");
  }

  function applyFilters() {
    state.query = els.query.value;
    state.category = els.category.value;
    state.audience = els.audience.value;
    state.start = els.start.value;
    state.end = els.end.value;
    state.fullText = Boolean(els.fullText && els.fullText.checked);
    if (state.fullText && !Object.keys(state.rawTexts).length) {
      els.count.textContent = "正在读取全文索引";
      loadRawIndex().then(() => render(state.items.filter(matches)));
      return;
    }
    render(state.items.filter(matches));
  }

  function bind() {
    [els.query, els.category, els.audience, els.start, els.end, els.fullText].filter(Boolean).forEach((el) => {
      el.addEventListener("input", applyFilters);
      el.addEventListener("change", applyFilters);
    });
    els.reset.addEventListener("click", () => {
      [els.query, els.category, els.audience, els.start, els.end].forEach((el) => {
        el.value = "";
      });
      if (els.fullText) els.fullText.checked = false;
      applyFilters();
    });
  }

  fetch(window.INFO_RSS_SEARCH_INDEX || "/assets/search-index.json")
    .then((response) => {
      if (!response.ok) throw new Error("search index not found");
      return response.json();
    })
    .then((items) => {
      state.items = items;
      fillSelect(els.category, uniqueValues("category"), "全部类别");
      fillSelect(els.audience, uniqueValues("audience"), "全部对象");
      bind();
      render(state.items);
    })
    .catch(() => {
      els.count.textContent = "索引未生成";
      els.results.innerHTML =
        '<p class="empty">还没有搜索索引。请先运行 <code>python scripts/build_search_index.py</code>。</p>';
    });
})();
