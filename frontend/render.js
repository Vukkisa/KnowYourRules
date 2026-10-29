// Renders assistant Markdown as sanitized HTML. Answers can echo text from the indexed documents
// or from the user's own message, so the HTML from marked is always cleaned by DOMPurify before
// it reaches the DOM. Shared by index.html and tests/frontend/sanitize_test.html.
if (window.marked) marked.setOptions({ breaks: true });

// Answers never need form controls; an injected <form action="https://..."> could collect input.
const FORBIDDEN_TAGS = ['form', 'input', 'button', 'textarea', 'select', 'option'];

// Returns sanitized HTML, or null if marked/DOMPurify did not load - the caller then shows plain
// text instead of ever inserting unsanitized HTML.
function renderAssistantMarkdown(text){
  if (!window.marked || !window.DOMPurify || !DOMPurify.isSupported) return null;
  return DOMPurify.sanitize(marked.parse(text), { USE_PROFILES: { html: true }, FORBID_TAGS: FORBIDDEN_TAGS });
}
