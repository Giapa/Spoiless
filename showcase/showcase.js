const chapter = document.querySelector('#chapter');
const label = document.querySelector('#chapter-label');
const result = document.querySelector('#boundary-result');
const states = {
  2: ['Chapter 2', 'Chapter 1 is available for questions. Chapter 2 and later stay unread.'],
  3: ['Chapter 3', 'Chapters 1 and 2 are available for questions. Chapter 3 stays unread.'],
  4: ['Finished book', 'All confirmed chapters are available for questions.'],
};
chapter.addEventListener('input', () => {
  const [name, explanation] = states[chapter.value];
  label.textContent = name;
  chapter.setAttribute('aria-valuetext', name);
  result.textContent = explanation;
});

if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
  const observer = new IntersectionObserver((entries) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.classList.add('revealing');
      observer.unobserve(entry.target);
    }
  }, { threshold: 0.12 });
  document.querySelectorAll('h1, h2, h3, .hero-copy > p, .hero-art img, .feature img, .feature p, .boundary, .closing p').forEach((element) => observer.observe(element));
}
