(function () {
  const rows = Array.from(document.querySelectorAll(".archive-row[data-date-range]"));
  const year = document.getElementById("archive-year");
  const month = document.getElementById("archive-month");
  const day = document.getElementById("archive-day");
  const reset = document.getElementById("archive-reset");
  const count = document.getElementById("archive-count");

  if (!rows.length || !year || !month || !day || !reset || !count) return;

  function primaryDate(row) {
    const value = row.dataset.dateRange || "";
    const match = value.match(/\d{8}/);
    return match ? match[0] : "";
  }

  const dates = rows
    .map((row) => primaryDate(row))
    .filter(Boolean)
    .map((value) => ({
      year: value.slice(0, 4),
      month: value.slice(4, 6),
      day: value.slice(6, 8),
    }));

  function fill(select, values, label) {
    const selected = select.value;
    select.innerHTML = `<option value="">${label}</option>`;
    Array.from(new Set(values))
      .sort()
      .forEach((value) => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      });
    if (Array.from(select.options).some((option) => option.value === selected)) {
      select.value = selected;
    }
  }

  function refreshOptions() {
    fill(year, dates.map((date) => date.year), "全部年份");
    fill(
      month,
      dates.filter((date) => !year.value || date.year === year.value).map((date) => date.month),
      "全部月份"
    );
    fill(
      day,
      dates
        .filter((date) => !year.value || date.year === year.value)
        .filter((date) => !month.value || date.month === month.value)
        .map((date) => date.day),
      "全部日期"
    );
  }

  function matches(row) {
    const value = primaryDate(row);
    if (!value) return false;
    if (year.value && value.slice(0, 4) !== year.value) return false;
    if (month.value && value.slice(4, 6) !== month.value) return false;
    if (day.value && value.slice(6, 8) !== day.value) return false;
    return true;
  }

  function apply() {
    refreshOptions();
    let visible = 0;
    rows.forEach((row) => {
      const ok = matches(row);
      row.hidden = !ok;
      if (ok) visible += 1;
    });
    count.textContent = `${visible} 条归档`;
  }

  [year, month, day].forEach((select) => {
    select.addEventListener("change", apply);
  });

  reset.addEventListener("click", () => {
    year.value = "";
    month.value = "";
    day.value = "";
    apply();
  });

  apply();
})();
