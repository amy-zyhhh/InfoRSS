(function () {
  const toc = document.getElementById("category-toc");
  const prose = document.querySelector(".home-prose");
  if (!toc || !prose) return;

  const headings = Array.from(prose.querySelectorAll("h2")).filter((heading) => {
    return heading.textContent.trim();
  });

  if (!headings.length) return;

  headings.forEach((heading) => {
    const text = heading.textContent.trim();
    if (!heading.id) {
      heading.id = text;
    }

    const link = document.createElement("a");
    link.href = `#${encodeURIComponent(heading.id)}`;
    link.textContent = text;
    toc.appendChild(link);
  });

  toc.hidden = false;

  prose.querySelectorAll("a[href^='http']").forEach((link) => {
    link.setAttribute("target", "_blank");
    link.setAttribute("rel", "noopener");
  });
})();
