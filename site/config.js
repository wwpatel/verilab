// Backend base URL for the public site's live API calls.
//
// Leave empty ("") when this site is served from the same origin as the
// backend (for example, mounted by app.py itself, or a same-domain proxy).
// Set it to the deployed backend's URL when this site is hosted separately
// (for example, a static Vercel or Netlify deploy pointing at a Render,
// Railway, or Fly.io backend), with no trailing slash:
//
//   window.VERILAB_API_BASE = "https://verilab-api.onrender.com";
//
// Editing this file is the only step needed to point a static deploy of
// site/ at a live backend; index.html itself does not need to change.
window.VERILAB_API_BASE = "";
