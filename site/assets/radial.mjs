// radial.mjs: the catalog chart's hover and keyboard layer. The chart is
// complete without it: every bar carries its name and count as a <title> and
// an aria-label, and the legend and the table below it carry the same facts.
// With it: one tab stop for the chart, the arrow keys (and Home, End) move
// between bars, and the bar under the pointer or the focus shows its name and
// count beside it. The bars grow in once, unless reduced motion is asked for.

const svg = document.getElementById("rd-svg");
const tip = document.getElementById("rd-tip");

if (svg && tip) {
  const bars = [...svg.querySelectorAll(".rd-bar")];
  const box = svg.parentElement;
  // the <title> is the no-script tooltip; the custom one replaces it here
  bars.forEach((b) => b.querySelector("title")?.remove());

  const show = (bar) => {
    bars.forEach((b) => b.classList.toggle("is-on", b === bar));
    const r = bar.getBoundingClientRect(), o = box.getBoundingClientRect();
    tip.textContent = bar.dataset.tip;
    tip.hidden = false;
    const half = Math.min(tip.offsetWidth / 2, o.width / 2);
    const x = Math.min(Math.max(r.left + r.width / 2 - o.left, half), o.width - half);
    tip.style.left = `${x}px`;
    tip.style.top = `${r.top - o.top}px`;
  };
  const hide = () => { tip.hidden = true; bars.forEach((b) => b.classList.remove("is-on")); };

  let current = 0;
  const focusBar = (i) => {
    bars[current].tabIndex = -1;
    current = (i + bars.length) % bars.length;
    bars[current].tabIndex = 0;
    bars[current].focus();
  };
  bars.forEach((b, i) => {
    b.addEventListener("pointerenter", () => show(b));
    b.addEventListener("pointerleave", () => { if (document.activeElement !== b) hide(); });
    b.addEventListener("focus", () => { current = i; show(b); });
    b.addEventListener("blur", hide);
  });
  svg.addEventListener("keydown", (e) => {
    const step = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
    if (step) { e.preventDefault(); focusBar(current + step); }
    else if (e.key === "Home") { e.preventDefault(); focusBar(0); }
    else if (e.key === "End") { e.preventDefault(); focusBar(bars.length - 1); }
    else if (e.key === "Escape") { hide(); }
  });

  const radial = svg.closest(".radial");
  if (radial && !matchMedia("(prefers-reduced-motion: reduce)").matches && "IntersectionObserver" in window) {
    radial.classList.add("pre");
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) { radial.classList.replace("pre", "grow"); io.disconnect(); }
    }, { threshold: 0.2 });
    io.observe(radial);
  }
}
