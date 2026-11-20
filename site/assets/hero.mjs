// hero.mjs: plays the conversion drawn in the first screen, one pack line at a
// time. Everything it shows is already in the page as the finished state (what
// a reader with JavaScript off, or with reduced motion, sees): the bytes of the
// Remote ID vector, the pack lines that read them, and the goat-xf output.
// site/bundle.py checks those values against the tree on every build.

const sig = document.getElementById("sig");
const reduce = matchMedia("(prefers-reduced-motion: reduce)");

if (sig && !reduce.matches) {
  const steps = [...sig.querySelectorAll(".sig-steps li")];
  const bytes = [...sig.querySelectorAll(".hb")];
  const outs = [...sig.querySelectorAll("[data-out]")];
  // The byte indexes a step reads, from its locator <word>:<first bit>:<bits>
  // (word_bytes 1, so bit n is in byte floor(n / 8)).
  const range = (li) => {
    if (!li.dataset.loc) return [];
    const [, first, len] = li.dataset.loc.split(":").map(Number);
    const out = [];
    for (let b = Math.floor(first / 8); b <= Math.floor((first + len - 1) / 8); b++) out.push(b);
    return out;
  };
  const finals = new Map(outs.map((o) => [o, o.textContent]));
  const STEP = 1500, HOLD = 4200;
  let timer = 0, i = -1;

  const reset = () => {
    sig.classList.add("playing");
    steps.forEach((s) => { s.classList.remove("on"); s.classList.add("wait"); });
    bytes.forEach((b) => b.classList.remove("on", "done"));
    outs.forEach((o) => { o.classList.remove("on"); o.classList.add("wait"); });
  };
  const type = (o) => {
    const full = finals.get(o);
    let n = 0;
    o.classList.remove("wait");
    o.classList.add("on");
    const tick = () => {
      o.textContent = full.slice(0, ++n);
      if (n < full.length) setTimeout(tick, 34);
    };
    o.textContent = "";
    tick();
  };
  const advance = () => {
    // finish the previous step
    if (i >= 0) {
      steps[i].classList.remove("on");
      range(steps[i]).forEach((b) => { bytes[b].classList.remove("on"); bytes[b].classList.add("done"); });
      outs.filter((o) => o.dataset.out === steps[i].dataset.step).forEach((o) => o.classList.remove("on"));
    }
    i++;
    if (i === steps.length) {
      timer = setTimeout(() => { reset(); i = -1; timer = setTimeout(advance, 700); }, HOLD);
      return;
    }
    const li = steps[i];
    li.classList.remove("wait");
    li.classList.add("on");
    range(li).forEach((b) => bytes[b].classList.add("on"));
    setTimeout(() => outs.filter((o) => o.dataset.out === li.dataset.step).forEach(type), 520);
    timer = setTimeout(advance, STEP);
  };

  reset();
  timer = setTimeout(advance, 600);
  // pause while the hero is off screen
  new IntersectionObserver(([e]) => {
    if (!e.isIntersecting) { clearTimeout(timer); timer = 0; }
    else if (!timer) { reset(); i = -1; timer = setTimeout(advance, 400); }
  }).observe(sig);
}
