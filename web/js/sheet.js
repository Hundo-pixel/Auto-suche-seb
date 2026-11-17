// iOS-artiges Bottom-Sheet mit Grabber und Wisch-zum-Schließen. Unterstützt gestapelte Inhalte (push/pop).
import { $ } from "./util.js";

const sheet = () => $("#sheet");
const backdrop = () => $("#backdrop");
const stack = [];
let onCloseCb = null;

function render(entry) {
  // Seiten dürfen Fabrikfunktionen sein -> beim Zurückkehren frisch aufgebaut
  const page = typeof entry === "function" ? entry() : entry;
  const el = sheet();
  el.innerHTML = `<div class="grabber"></div>
    <div class="sheet-head">
      <button data-act="left">${page.left ?? (stack.length > 1 ? "‹ Zurück" : "Abbrechen")}</button>
      <h2>${page.title}</h2>
      <button data-act="right">${page.right ?? "Fertig"}</button>
    </div>
    <div class="sheet-body">${page.html}</div>
    ${page.foot ? `<div class="sheet-foot">${page.foot}</div>` : ""}`;
  el.querySelector('[data-act="left"]').onclick = () => (page.onLeft ? page.onLeft() : stack.length > 1 ? pop() : close());
  el.querySelector('[data-act="right"]').onclick = () => (page.onRight ? page.onRight() : stack.length > 1 ? pop() : close());
  page.mount?.(el);
}

export function open(page, onClose) {
  stack.length = 0;
  stack.push(page);
  onCloseCb = onClose || null;
  render(page);
  requestAnimationFrame(() => {
    backdrop().classList.add("show");
    sheet().classList.add("show");
  });
  document.body.style.overflow = "hidden";
}

export function push(page) { stack.push(page); render(page); }
export function pop() {
  stack.pop();
  if (stack.length) render(stack[stack.length - 1]);
  else close();
}
export function refresh() { if (stack.length) render(stack[stack.length - 1]); }
export function isOpen() { return sheet().classList.contains("show"); }

export function close() {
  sheet().classList.remove("show");
  backdrop().classList.remove("show");
  document.body.style.overflow = "";
  const cb = onCloseCb;
  onCloseCb = null;
  stack.length = 0;
  cb?.();
}

export function initSheet() {
  backdrop().addEventListener("click", close);
  // Wischen nach unten am Kopfbereich schließt das Sheet
  const el = sheet();
  let y0 = null, dy = 0;
  el.addEventListener("touchstart", (e) => {
    const inHead = e.target.closest(".grabber, .sheet-head");
    const body = el.querySelector(".sheet-body");
    if (!inHead && body && body.scrollTop > 0) return;
    if (!inHead && !e.target.closest(".sheet-body")) return;
    y0 = e.touches[0].clientY; dy = 0;
  }, { passive: true });
  el.addEventListener("touchmove", (e) => {
    if (y0 == null) return;
    dy = e.touches[0].clientY - y0;
    const body = el.querySelector(".sheet-body");
    if (dy > 0 && (!body || body.scrollTop <= 0)) {
      el.classList.add("dragging");
      el.style.transform = `translateY(${dy}px)`;
    }
  }, { passive: true });
  el.addEventListener("touchend", () => {
    if (y0 == null) return;
    el.classList.remove("dragging");
    el.style.transform = "";
    if (dy > 110) close();
    y0 = null;
  });
}
