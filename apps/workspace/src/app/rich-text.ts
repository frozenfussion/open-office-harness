// SPDX-License-Identifier: AGPL-3.0-only
import createDOMPurify from 'dompurify';
import { Marked, Tokens } from 'marked';
import { renderToString } from 'katex';

interface MathToken extends Tokens.Generic {
  text: string;
  display: boolean;
  closed: boolean;
}
interface Formula { text: string; display: boolean }
export interface RichText { fragment: DocumentFragment; codeBlocks: string[] }
const forbidden = ['img', 'svg', 'math', 'style', 'iframe', 'form', 'input', 'video', 'audio', 'object', 'embed'];

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]!));
}
function escaped(source: string, index: number): boolean {
  let slashes = 0;
  while (index > 0 && source[--index] === '\\') slashes++;
  return slashes % 2 === 1;
}
function mathToken(source: string): MathToken | undefined {
  const open = ['$$', '\\[', '\\(', '$'].find(delimiter => source.startsWith(delimiter));
  if (!open || (open === '$' && /\s/u.test(source[1] ?? ''))) return undefined;
  const close = open === '\\[' ? '\\]' : open === '\\(' ? '\\)' : open;
  let end = source.indexOf(close, open.length);
  while (end !== -1 && (escaped(source, end) ||
    (open === '$' && (/\s/u.test(source[end - 1]) || /[0-9]/u.test(source[end + 1] ?? ''))))) {
    end = source.indexOf(close, end + close.length);
  }
  return {
    type: 'oohMath', raw: end === -1 ? source : source.slice(0, end + close.length),
    text: end === -1 ? source : source.slice(open.length, end),
    display: open === '$$' || open === '\\[', closed: end !== -1,
  };
}

export function renderRichText(source: string): RichText {
  const formulas: Formula[] = [];
  const codeBlocks: string[] = [];
  const markdown = new Marked({gfm: true, async: false});
  const renderMath = (generic: Tokens.Generic): string => {
    const token = generic as MathToken;
    if (!token.closed) return `<span class="ooh-math-pending">${escapeHtml(token.raw)}</span>`;
    const index = formulas.push({text: token.text, display: token.display}) - 1;
    return `<span data-ooh-math="${index}"></span>`;
  };
  markdown.use({
    renderer: {
      html: ({text}) => escapeHtml(text),
      image: () => '',
      code: ({text}) => {
        const index = codeBlocks.push(text) - 1;
        return `<pre><code data-ooh-code="${index}">${escapeHtml(text)}</code></pre>`;
      },
    },
    extensions: [
      {
        name: 'oohMath', level: 'block',
        start: source => source.match(/(?:^|\n) {0,3}(?:\$\$|\\\[)/)?.index,
        tokenizer: source => {
          const indent = source.match(/^ {0,3}(?=\$\$|\\\[)/)?.[0];
          if (indent === undefined) return undefined;
          const token = mathToken(source.slice(indent.length));
          if (!token) return undefined;
          if (token.closed && !/^(?:[ \t]*\n|[ \t]*$)/.test(source.slice(indent.length + token.raw.length))) return undefined;
          return {...token, raw: indent + token.raw};
        },
        renderer: renderMath,
      },
      {
        name: 'oohMath', level: 'inline',
        start: source => source.match(/\$|\\\(|\\\[/)?.index,
        tokenizer: source => mathToken(source), renderer: renderMath,
      },
    ],
  });
  const purify = createDOMPurify(window);
  purify.addHook('afterSanitizeAttributes', node => {
    if (node.nodeName.toLowerCase() !== 'a') return;
    const href = node.getAttribute('href');
    if (href) {
      try {
        if (!['http:', 'https:', 'mailto:'].includes(new URL(href).protocol)) node.removeAttribute('href');
      } catch { node.removeAttribute('href'); }
    }
    node.setAttribute('target', '_blank');
    node.setAttribute('rel', 'noopener noreferrer');
  });
  const fragment = purify.sanitize(markdown.parse(source, {async: false}), {
    USE_PROFILES: {html: true}, FORBID_TAGS: forbidden, FORBID_ATTR: ['style'], RETURN_DOM_FRAGMENT: true,
  });
  for (const placeholder of fragment.querySelectorAll('[data-ooh-math]')) {
    const formula = formulas[Number(placeholder.getAttribute('data-ooh-math'))];
    if (!formula) { placeholder.remove(); continue; }
    // Only our KaTeX output enters this separate, broader sanitizer profile.
    const rendered = renderToString(formula.text, {
      displayMode: formula.display, throwOnError: false, trust: false,
      strict: 'ignore', errorColor: 'var(--signal-red)',
    });
    placeholder.replaceWith(purify.sanitize(rendered, {
      USE_PROFILES: {html: true, mathMl: true, svg: true},
      FORBID_TAGS: forbidden.filter(tag => tag !== 'math' && tag !== 'svg'), RETURN_DOM_FRAGMENT: true,
    }));
  }
  for (const table of fragment.querySelectorAll('table')) {
    const wrapper = document.createElement('div');
    wrapper.className = 'ooh-table-scroll';
    wrapper.tabIndex = 0;
    wrapper.setAttribute('role', 'region');
    wrapper.setAttribute('aria-label', 'Chat table');
    table.replaceWith(wrapper);
    wrapper.append(table);
  }
  return {fragment, codeBlocks};
}
