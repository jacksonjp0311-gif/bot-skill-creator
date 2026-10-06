(function () {
  try {
    var query = new URLSearchParams(location.search).get('theme');
    var saved = localStorage.getItem('bsc-theme');
    var theme = query === 'dark' || query === 'light' ? query : (saved === 'dark' || saved === 'light' ? saved : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'));
    document.documentElement.dataset.theme = theme;
  } catch (error) {
    document.documentElement.dataset.theme = 'light';
  }
})();
