const chapter = document.querySelector('#chapter');
const label = document.querySelector('#chapter-label');
const result = document.querySelector('#boundary-result');
const states = {
  2: ['Chapter 2', 'Chapter 1 is available for questions. Chapter 2 and later stay unread.'],
  3: ['Chapter 3', 'Chapters 1 and 2 are available for questions. Chapter 3 stays unread.'],
  4: ['Finished book', 'All detected chapters are available for questions.'],
};
chapter.addEventListener('input', () => {
  const [name, explanation] = states[chapter.value];
  label.textContent = name;
  chapter.setAttribute('aria-valuetext', name);
  result.textContent = explanation;
});

