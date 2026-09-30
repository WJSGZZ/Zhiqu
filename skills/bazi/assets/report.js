(() => {
  const details = () => Array.from(document.querySelectorAll("details"));
  const setAll = (open) => details().forEach((item) => { item.open = open; });
  const menuButton = document.querySelector("[data-action='menu']");
  const menuPanel = document.querySelector(".sidebar-panel");
  const search = document.querySelector("[data-search]");
  const searchStatus = document.querySelector("[data-search-status]");
  const searchEmpty = document.querySelector("[data-search-empty]");
  const sections = Array.from(document.querySelectorAll("[data-search-section]"));
  const navLinks = Array.from(document.querySelectorAll("[data-nav-target]"));

  const setMenu = (open) => {
    if (!menuButton || !menuPanel) return;
    menuPanel.dataset.open = String(open);
    menuButton.setAttribute("aria-expanded", String(open));
    menuButton.textContent = open ? "关闭" : "目录";
  };

  const clearSearch = () => {
    sections.forEach((section) => {
      section.hidden = false;
      section.classList.remove("search-match");
      section.querySelectorAll("details").forEach((item) => {
        item.hidden = false;
        if (item.dataset.searchOpened === "true") item.open = false;
        delete item.dataset.searchOpened;
      });
    });
    navLinks.forEach((link) => { link.hidden = false; });
    if (searchStatus) searchStatus.textContent = `共 ${sections.length} 个章节`;
    if (searchEmpty) searchEmpty.hidden = true;
  };

  const runSearch = () => {
    const query = search?.value.trim().toLocaleLowerCase("zh-CN") || "";
    if (!query) {
      clearSearch();
      return;
    }
    let matches = 0;
    sections.forEach((section) => {
      const sectionMatches = section.textContent.toLocaleLowerCase("zh-CN").includes(query);
      section.hidden = !sectionMatches;
      section.classList.toggle("search-match", sectionMatches);
      if (sectionMatches) matches += 1;
      const sectionDetails = Array.from(section.querySelectorAll("details"));
      sectionDetails.forEach((item) => {
        const detailMatches = item.textContent.toLocaleLowerCase("zh-CN").includes(query);
        item.hidden = sectionMatches && !detailMatches;
        if (detailMatches && !item.open) {
          item.open = true;
          item.dataset.searchOpened = "true";
        }
      });
    });
    navLinks.forEach((link) => {
      link.hidden = document.getElementById(link.dataset.navTarget)?.hidden ?? false;
    });
    if (searchStatus) searchStatus.textContent = matches ? `找到 ${matches} 个章节` : "没有匹配章节";
    if (searchEmpty) searchEmpty.hidden = matches !== 0;
  };

  document.querySelector("[data-action='expand']")?.addEventListener("click", () => setAll(true));
  document.querySelector("[data-action='collapse']")?.addEventListener("click", () => setAll(false));
  document.querySelector("[data-action='top']")?.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  document.querySelector("[data-action='print']")?.addEventListener("click", () => window.print());
  menuButton?.addEventListener("click", () => setMenu(menuButton.getAttribute("aria-expanded") !== "true"));
  navLinks.forEach((link) => link.addEventListener("click", () => setMenu(false)));
  search?.addEventListener("input", runSearch);
  search?.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      search.value = "";
      clearSearch();
      search.blur();
    }
  });

  const updateProgress = () => {
    const height = document.documentElement.scrollHeight - window.innerHeight;
    const percent = height > 0 ? Math.min(100, Math.max(0, window.scrollY / height * 100)) : 0;
    const bar = document.querySelector("[data-progress]");
    if (bar) bar.style.width = `${percent}%`;
  };
  window.addEventListener("scroll", updateProgress, { passive: true });
  updateProgress();

  if ("IntersectionObserver" in window) {
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (!visible) return;
      navLinks.forEach((link) => link.classList.toggle("active", link.dataset.navTarget === visible.target.id));
    }, { rootMargin: "-18% 0px -68% 0px", threshold: [0, .15, .5] });
    sections.forEach((section) => observer.observe(section));
  }

  let printState = [];
  window.addEventListener("beforeprint", () => {
    printState = details().map((item) => item.open);
    setAll(true);
  });
  window.addEventListener("afterprint", () => {
    details().forEach((item, index) => { item.open = printState[index] ?? item.open; });
  });
})();
