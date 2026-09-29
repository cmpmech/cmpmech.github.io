// Videos with a data-dark source switch with the colour scheme (light is the default src)
const dark = matchMedia("(prefers-color-scheme: dark)");
const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
const themed = document.querySelectorAll("video[data-dark]");
for (const video of themed) {
  video.dataset.light = video.getAttribute("src");
  video.dataset.lightPoster = video.getAttribute("poster") || "";
}
const applyTheme = () => {
  for (const video of themed) {
    const src = dark.matches ? video.dataset.dark : video.dataset.light;
    const poster = dark.matches ? video.dataset.darkPoster : video.dataset.lightPoster;
    if (poster) video.poster = poster;
    if (video.getAttribute("src") !== src) {
      video.src = src;
      if (!still) video.play().catch(() => {});
    }
  }
};
applyTheme();
dark.addEventListener("change", applyTheme);

// Autoplaying videos: respect reduced-motion preferences, and where the browser blocks
// autoplay (e.g. phones in power-saving mode), start them on the first interaction
const videos = document.querySelectorAll("video[autoplay]");
if (still) {
  for (const video of videos) {
    video.removeAttribute("autoplay");
    video.pause();
  }
} else {
  for (const video of videos) {
    video.muted = true;
    video.play().catch(() => {
      const start = () => video.play().catch(() => {});
      for (const type of ["pointerup", "touchend", "keydown"]) {
        addEventListener(type, start, { once: true, passive: true });
      }
    });
  }
}
