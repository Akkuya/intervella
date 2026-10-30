;(() => {
  let choice = 'system'
  try {
    const saved = localStorage.getItem('utscvacant.appearance')
    if (saved === 'light' || saved === 'dark') choice = saved
  } catch {}
  document.documentElement.dataset.appearance = choice
  document.documentElement.dataset.theme =
    choice === 'system'
      ? matchMedia('(prefers-color-scheme: dark)').matches
        ? 'dark'
        : 'light'
      : choice
})()
