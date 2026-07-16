(function () {
  const state = {
    items: [],
    query: "",
    category: "",
    audience: "",
    start: "",
    end: "",
  };

  const els = {
    query: document.getElementById("search-input"),
    category: document.getElementById("category-filter"),
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
    const haystack = normalize(item.text);
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
        return `
          <article class="notice-card">
            <div class="notice-meta">
              <span>${escapeHtml(item.category)}</span>
              <time>${escapeHtml(item.published_at)}</time>
            </div>
            <h3><a href="${escapeHtml(item.page_url)}">${escapeHtml(item.title)}</a></h3>
            <p>${escapeHtml(item.summary)}</p>
            <div class="notice-detail">
              <span>适用对象：${escapeHtml(item.audience || "未标注")}</span>
              <a href="${escapeHtml(item.source_url)}" target="_blank" rel="noopener">原文</a>
            </div>
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
    render(state.items.filter(matches));
  }

  function bind() {
    [els.query, els.category, els.audience, els.start, els.end].forEach((el) => {
      el.addEventListener("input", applyFilters);
      el.addEventListener("change", applyFilters);
    });
    els.reset.addEventListener("click", () => {
      [els.query, els.category, els.audience, els.start, els.end].forEach((el) => {
        el.value = "";
      });
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
