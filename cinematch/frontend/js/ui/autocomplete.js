// ============================================================================
// CineMatch — ui/autocomplete.js
// A multi-select search box with suggestions (ARIA combobox pattern).
// Used by the Mood Mixer for reference films, directors and actors.
// ============================================================================

import { el, esc, debounce } from "../utils.js";
import { icon } from "./icons.js";

let acCounter = 0;

/**
 * autocomplete({
 *   label, placeholder,
 *   search: async (q) => [option],          // options to suggest
 *   optionHTML: (option) => "<...>",         // how a suggestion looks
 *   tokenHTML: (value) => "<...>",           // how a chosen value looks
 *   keyOf: (optionOrValue) => string,        // identity
 *   toValue: (option) => value,              // what gets stored
 *   values: [value], onChange: (values) => {}, max
 * })
 */
export function autocomplete(opts) {
  const id = `ac-${++acCounter}`;
  let values = [...(opts.values || [])];
  let options = [];
  let activeIndex = -1;
  let lastQuery = "";

  const node = el(`
    <div class="ac">
      <div class="ac__tokens" aria-label="${esc(opts.label)} chosen"></div>
      <input class="input" type="text" role="combobox" aria-expanded="false" aria-autocomplete="list"
             aria-controls="${id}-list" aria-label="${esc(opts.label)}" placeholder="${esc(opts.placeholder || "")}" autocomplete="off" spellcheck="false">
      <div class="ac__list" id="${id}-list" role="listbox" hidden></div>
    </div>`);
  const input = node.querySelector("input");
  const list = node.querySelector(".ac__list");
  const tokens = node.querySelector(".ac__tokens");
  if (opts.tokens === false) tokens.remove();

  function renderTokens() {
    if (opts.tokens === false) return;
    tokens.innerHTML = values.map((v, i) => `
      <span class="token ${opts.tokenClass || ""}">${opts.tokenHTML(v)}
        <button type="button" class="token__x" data-i="${i}" aria-label="Remove ${esc(opts.keyOf(v))}">${icon("x")}</button>
      </span>`).join("");
    tokens.querySelectorAll(".token__x").forEach((b) => b.addEventListener("click", () => {
      values.splice(Number(b.dataset.i), 1);
      renderTokens();
      opts.onChange?.([...values]);
      input.focus();
    }));
    input.disabled = opts.max ? values.length >= opts.max : false;
    if (input.disabled) input.placeholder = `Up to ${opts.max}`;
    else input.placeholder = opts.placeholder || "";
  }

  function close() {
    list.hidden = true;
    input.setAttribute("aria-expanded", "false");
    input.removeAttribute("aria-activedescendant");
    activeIndex = -1;
  }

  function renderList() {
    const chosen = new Set(values.map(opts.keyOf));
    options = options.filter((o) => !chosen.has(opts.keyOf(o)));
    if (!options.length) {
      list.innerHTML = lastQuery ? `<div class="ac__empty">No matches for "${esc(lastQuery)}"</div>` : "";
      list.hidden = !lastQuery;
      input.setAttribute("aria-expanded", String(!list.hidden));
      return;
    }
    list.innerHTML = options.map((o, i) => `<div class="ac__opt" role="option" id="${id}-o${i}" data-i="${i}" aria-selected="${i === activeIndex}">${opts.optionHTML(o)}</div>`).join("");
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    list.querySelectorAll(".ac__opt").forEach((n) => {
      n.addEventListener("mousedown", (e) => { e.preventDefault(); choose(Number(n.dataset.i)); });
    });
  }

  function highlight(i) {
    activeIndex = i;
    list.querySelectorAll(".ac__opt").forEach((n, j) => n.setAttribute("aria-selected", String(j === i)));
    if (i >= 0) {
      input.setAttribute("aria-activedescendant", `${id}-o${i}`);
      list.querySelector(`#${id}-o${i}`)?.scrollIntoView({ block: "nearest" });
    }
  }

  function choose(i) {
    const option = options[i];
    if (!option) return;
    values.push(opts.toValue ? opts.toValue(option) : option);
    input.value = "";
    lastQuery = "";
    close();
    renderTokens();
    opts.onChange?.([...values]);
    if (!input.disabled) input.focus();
  }

  const runSearch = debounce(async (q) => {
    lastQuery = q;
    if (!q) { close(); return; }
    try {
      const found = await opts.search(q);
      if (q !== input.value.trim()) return; // a newer query is on its way
      options = found || [];
      activeIndex = options.length ? 0 : -1;
      renderList();
    } catch {
      options = [];
      close();
    }
  }, 220);

  input.addEventListener("input", () => runSearch(input.value.trim()));
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" && !list.hidden) { e.preventDefault(); highlight(Math.min(options.length - 1, activeIndex + 1)); }
    else if (e.key === "ArrowUp" && !list.hidden) { e.preventDefault(); highlight(Math.max(0, activeIndex - 1)); }
    else if (e.key === "Enter" && !list.hidden && activeIndex >= 0) { e.preventDefault(); choose(activeIndex); }
    else if (e.key === "Escape" && !list.hidden) { e.preventDefault(); e.stopPropagation(); close(); }
    else if (e.key === "Backspace" && !input.value && values.length) {
      values.pop();
      renderTokens();
      opts.onChange?.([...values]);
    }
  });
  input.addEventListener("blur", () => setTimeout(close, 120));

  renderTokens();
  node.setValues = (next) => { values = [...next]; renderTokens(); };
  node.refreshTokens = renderTokens;
  return node;
}
