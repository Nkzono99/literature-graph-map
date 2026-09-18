const form = document.querySelector('.paper-filter');
if (form) {
  const search = document.querySelector('#paper-search');
  const groupFilter = document.querySelector('#group-filter');
  const groups = [...document.querySelectorAll('.paper-group')];
  const papers = [...document.querySelectorAll('.paper')];
  const normalize = text => text.normalize('NFKC').toLocaleLowerCase();
  const searchable = new Map(papers.map(paper => [paper, normalize(`${paper.textContent} ${paper.dataset.authors}`)]));
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
  form.addEventListener('reset', () => {
    search.value = '';
    groupFilter.value = '';
    applyFilter();
  });
  // Following a paper/group link should reveal its target even after filtering.
  const revealTarget = (hash = location.hash) => {
    const target = document.getElementById(hash.slice(1));
    if (target?.matches('.paper, .paper-group')) {
      form.reset();
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

const graphs = [...document.querySelectorAll('.graph')];
if (graphs.length) {
  try {
    const { default: mermaid } = await import('https://cdn.jsdelivr.net/npm/mermaid@11.12.0/dist/mermaid.esm.min.mjs');
    mermaid.initialize({
      startOnLoad: false, securityLevel: 'strict', theme: 'base',
      themeVariables: { primaryColor: '#edf2ee', primaryTextColor: '#23313a', primaryBorderColor: '#8daba0', lineColor: '#537c72', fontSize: '14px' },
      flowchart: { useMaxWidth: false, htmlLabels: false },
    });
    for (const [index, graph] of graphs.entries()) {
      const source = graph.querySelector('code').textContent;
      const canvas = graph.querySelector('.graph-canvas');
      try {
        const { svg } = await mermaid.render(`graph-${index}`, source);
        canvas.innerHTML = svg;
        // Use native SVG links so paper navigation also works with the keyboard.
        for (const node of canvas.querySelectorAll('g.node')) {
          const paperClass = [...node.classList].find(name => name.startsWith('paper_'));
          const paperId = paperClass.slice('paper_'.length);
          const paper = document.getElementById(paperId);
          const link = document.createElementNS('http://www.w3.org/2000/svg', 'a');
          link.setAttribute('href', `#${paperId}`);
          link.setAttribute('aria-label', `${paper.querySelector('.paper-kicker a').textContent} の文献へ`);
          node.replaceWith(link);
          link.append(node);
        }
        canvas.hidden = false;
      } catch {
        graph.querySelector('details').open = true;
      }
    }
  } catch {
    for (const graph of graphs) graph.querySelector('details').open = true;
  }
}
