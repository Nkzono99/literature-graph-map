const form = document.querySelector('.paper-filter');
if (form) {
  const search = document.querySelector('#paper-search');
  const groupFilter = document.querySelector('#group-filter');
  const yearOrder = document.querySelector('#year-order');
  const groups = [...document.querySelectorAll('.paper-group')];
  const papers = [...document.querySelectorAll('.paper')];
  const normalize = text => text.normalize('NFKC').toLocaleLowerCase();
  const searchable = new Map(papers.map(paper => [paper, normalize(`${paper.textContent} ${paper.dataset.authors}`)]));
  const sortPapers = () => {
    for (const group of groups) {
      const members = papers.filter(paper => paper.parentElement === group);
      members.sort((a, b) => {
        if (!a.dataset.year) return b.dataset.year ? 1 : 0;
        if (!b.dataset.year) return -1;
        return (Number(a.dataset.year) - Number(b.dataset.year)) * (yearOrder.value === 'newest' ? -1 : 1);
      });
      group.append(...members);
    }
  };
  const applyFilter = () => {
    const terms = normalize(search.value).trim().split(/\s+/).filter(Boolean);
    let count = 0;
    for (const group of groups) {
      let groupCount = 0;
      for (const paper of group.querySelectorAll('.paper')) {
        const visible = (!groupFilter.value || group.dataset.group === groupFilter.value)
          && terms.every(term => searchable.get(paper).includes(term));
        paper.hidden = !visible;
        if (visible) groupCount++;
      }
      group.hidden = groupCount === 0;
      count += groupCount;
    }
    document.querySelector('#paper-count').textContent = `${count} / ${papers.length}件`;
    document.querySelector('#no-results').hidden = count > 0;
  };
  form.hidden = false;
  form.addEventListener('submit', event => event.preventDefault());
  search.addEventListener('input', applyFilter);
  groupFilter.addEventListener('change', applyFilter);
  yearOrder.addEventListener('change', sortPapers);
  const clearFilters = () => {
    search.value = '';
    groupFilter.value = '';
    applyFilter();
  };
  form.addEventListener('reset', () => {
    clearFilters();
    yearOrder.value = 'oldest';
    sortPapers();
  });
  // Following a paper/group link should reveal its target even after filtering.
  const revealTarget = (hash = location.hash) => {
    const target = document.getElementById(hash.slice(1));
    if (target?.matches('.paper, .paper-group')) {
      clearFilters();
      target.scrollIntoView();
    }
  };
  window.addEventListener('hashchange', () => revealTarget());
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href^="#"]');
    if (link) revealTarget(link.getAttribute('href'));
  });
  revealTarget();
}
