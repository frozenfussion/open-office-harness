// SPDX-License-Identifier: AGPL-3.0-only
import { describe, expect, it, vi } from 'vitest';
import { renderRichText } from './rich-text';

describe('safe Markdown and maths', () => {
  it('renders headings, lists, tables, links, inline code and fenced code', () => {
    const result = renderRichText('# Heading\n\n- First\n- Second\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\n[Link](https://example.invalid) and `inline`\n\n```js\nconst n = 1;\n```');
    expect(result.fragment.querySelector('h1')?.textContent).toBe('Heading');
    expect(result.fragment.querySelectorAll('li').length).toBe(2);
    expect(result.fragment.querySelectorAll('td').length).toBe(2);
    expect(result.fragment.querySelector('p code')?.textContent).toBe('inline');
    expect(result.fragment.querySelector('pre code')?.textContent).toBe('const n = 1;');
    expect(result.codeBlocks).toEqual(['const n = 1;']);
    const link = result.fragment.querySelector('a')!;
    expect(link.getAttribute('target')).toBe('_blank');
    expect(link.getAttribute('rel')).toBe('noopener noreferrer');
  });
  it.each(['$x^2$', '\\(x^2\\)', '$$x^2$$', '\\[x^2\\]'])('renders the maths delimiter %s', source => {
    const result = renderRichText(source);
    expect(result.fragment.querySelector('.katex')).not.toBeNull();
    expect(result.fragment.querySelector('math')).not.toBeNull();
    expect(Boolean(result.fragment.querySelector('.katex-display'))).toBe(source.startsWith('$$') || source.startsWith('\\['));
  });
  it.each(['$x^2', '$$x^2', '\\(x^2', '\\[x^2'])('leaves unfinished maths as text: %s', source => {
    const result = renderRichText(source);
    expect(result.fragment.querySelector('.ooh-math-pending')?.textContent).toBe(source);
    expect(result.fragment.querySelector('.katex')).toBeNull();
  });
  it('leaves maths inside inline and fenced code unchanged', () => {
    const result = renderRichText('`$x$`\n\n```\n$$y$$\n```');
    expect(result.fragment.querySelector('.katex')).toBeNull();
    expect(result.fragment.querySelector('p code')?.textContent).toBe('$x$');
    expect(result.codeBlocks).toEqual(['$$y$$']);
  });
  it('keeps raw HTML inert and removes external images', () => {
    const alert = vi.spyOn(window, 'alert').mockImplementation(() => undefined);
    const source = '<script>alert(1)</script>\n\n<img src="https://outside.invalid/tracker" onerror="alert(1)">\n\n![outside](https://outside.invalid/tracker)\n\n<b>raw</b> **bold**\n\n<svg onload="alert(1)"></svg><math><mtext>raw</mtext></math>';
    const host = document.createElement('div');
    host.append(renderRichText(source).fragment);
    document.body.append(host);
    expect(host.querySelector('script,img,svg,math,[onerror],[onload],b')).toBeNull();
    expect(host.querySelector('strong')?.textContent).toBe('bold');
    expect(alert).not.toHaveBeenCalled();
    host.remove(); alert.mockRestore();
  });
  it('allows only HTTP, HTTPS and mailto links', () => {
    const result = renderRichText('[bad](javascript:alert%281%29) [data](data:text/html,bad) [ftp](ftp://example.invalid) [relative](/local) [mail](mailto:test@example.invalid) [web](http://example.invalid)');
    expect([...result.fragment.querySelectorAll('a[href]')].map(link => link.getAttribute('href')))
      .toEqual(['mailto:test@example.invalid', 'http://example.invalid']);
  });
  it('does not trust KaTeX commands and never logs model text', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const result = renderRichText('$\\includegraphics{https://outside.invalid/image}$ $\\href{javascript:alert(1)}{bad}$ $\\unknowncommand$');
    expect(result.fragment.querySelector('img,iframe,a[href]')).toBeNull();
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });
});
