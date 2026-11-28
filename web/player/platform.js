// Older embedded Chromium hosts implement append() but omit replaceChildren().
for (const target of [Element.prototype, DocumentFragment.prototype]) {
  if (!target.replaceChildren) {
    Object.defineProperty(target, 'replaceChildren', {
      configurable: true, writable: true,
      value: function (...nodes) {
        const next = this.ownerDocument.createDocumentFragment();
        next.append(...nodes);
        while (this.firstChild) this.removeChild(this.firstChild);
        this.appendChild(next);
      }
    });
  }
}
