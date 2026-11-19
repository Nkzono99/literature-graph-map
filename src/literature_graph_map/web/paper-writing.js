const levelSelect = document.querySelector('#writing-level');
const patternSelect = document.querySelector('#writing-pattern');
const draft = document.querySelector('#writing-draft');
const choice = document.querySelector('#writing-choice');
const saveButton = document.querySelector('#writing-save');
const levels = [...document.querySelectorAll('.writing-level')];

function currentPattern() {
  return levels[levelSelect.selectedIndex].querySelectorAll('.writing-pattern')[patternSelect.selectedIndex];
}

function showChoice() {
  choice.textContent = currentPattern().querySelector('.pattern-use').textContent;
}

function showLevel() {
  const patterns = levels[levelSelect.selectedIndex].querySelectorAll('.writing-pattern');
  patternSelect.replaceChildren(...Array.from(patterns, pattern =>
    new Option(pattern.querySelector('summary').textContent)
  ));
  showChoice();
}

function updateSaveButton() {
  saveButton.disabled = !draft.value.trim();
}

levelSelect.addEventListener('change', showLevel);
patternSelect.addEventListener('change', showChoice);
draft.addEventListener('input', updateSaveButton);
document.querySelector('#writing-insert').addEventListener('click', () => {
  const pattern = currentPattern();
  const expanded = document.querySelector('#writing-expand').checked;
  const template = expanded ? pattern.querySelector('.pattern-full') : null;
  let text = (template ?? pattern.querySelector('.pattern-plan')).textContent;
  const start = draft.selectionStart;
  const end = draft.selectionEnd;
  const appendBlock = start === end && end === draft.value.length && levelSelect.value !== '文';
  if (appendBlock && draft.value && !draft.value.endsWith('\n')) text = '\n\n' + text;
  draft.setRangeText(text, start, end, 'end');
  draft.focus();
  updateSaveButton();
});
saveButton.addEventListener('click', () => {
  const file = new Blob([draft.value], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(file);
  const link = document.createElement('a');
  link.href = url;
  link.download = 'manuscript.md';
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

showLevel();
updateSaveButton();
document.querySelector('#compose').hidden = false;
