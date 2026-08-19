/* App shell: auth guard, sidebar (exactly Dashboard, Stored Protocols,
   Settings, in that order), and top bar, shared by every authenticated
   page. An unauthenticated visitor hitting any app page is redirected to
   sign in before any page content is shown. */

window.VerilabShell = (function () {
  const ICONS = {
    dashboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="8" height="9" rx="1.5"/><rect x="13" y="3" width="8" height="5" rx="1.5"/><rect x="13" y="12" width="8" height="9" rx="1.5"/><rect x="3" y="16" width="8" height="5" rx="1.5"/></svg>',
    protocols: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2h9l5 5v15H6z"/><path d="M15 2v5h5"/><line x1="9" y1="13" x2="16" y2="13"/><line x1="9" y1="17" x2="16" y2="17"/></svg>',
    settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
  };

  const NAV_ITEMS = [
    { id: 'dashboard', label: 'Dashboard', href: '/site/app/dashboard.html', icon: ICONS.dashboard },
    { id: 'protocols', label: 'Stored Protocols', href: '/site/app/protocols.html', icon: ICONS.protocols },
    { id: 'settings', label: 'Settings', href: '/site/app/settings.html', icon: ICONS.settings },
  ];

  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (k === 'html') node.innerHTML = v;
      else if (k.startsWith('on')) node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v);
    }
    for (const c of (children || [])) {
      if (c == null) continue;
      node.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
    }
    return node;
  }

  function initials(name, email) {
    const source = (name || email || '?').trim();
    const parts = source.split(/\s+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return source.slice(0, 2).toUpperCase();
  }

  async function signOut() {
    try {
      await fetch('/api/auth/signout', { method: 'POST', credentials: 'include' });
    } finally {
      window.location.href = '/site/index.html';
    }
  }

  function renderSidebar(activePage) {
    const sidebar = document.getElementById('appSidebar');
    if (!sidebar) return;
    sidebar.innerHTML = '';
    sidebar.appendChild(el('a', { href: '/site/index.html', class: 'sidebar-wordmark' }, ['VERILAB']));
    const nav = el('nav', { class: 'sidebar-nav', 'aria-label': 'App navigation' }, []);
    for (const item of NAV_ITEMS) {
      const link = el('a', {
        href: item.href, class: 'sidebar-link',
        html: '<span aria-hidden="true">' + item.icon + '</span><span class="label-text">' + item.label + '</span>',
      }, []);
      if (item.id === activePage) link.setAttribute('aria-current', 'page');
      nav.appendChild(link);
    }
    sidebar.appendChild(nav);
  }

  function renderTopbar(pageTitle, user) {
    const topbar = document.getElementById('appTopbar');
    if (!topbar) return;
    topbar.innerHTML = '';
    topbar.appendChild(el('h1', {}, [pageTitle]));

    const signOutBtn = el('button', { type: 'button', class: 'btn btn-plain', onclick: signOut }, ['Sign out']);

    const account = el('div', { class: 'topbar-account' }, [
      el('div', { class: 'avatar', 'aria-hidden': 'true' }, [initials(user.display_name, user.email)]),
      el('div', { class: 'who' }, [
        user.display_name,
        el('span', { class: 'email' }, [user.email]),
      ]),
      signOutBtn,
    ]);
    topbar.appendChild(account);
  }

  // Breadcrumbs reinforce where a user is inside the three-tab structure.
  // Default is just the current tab's own name; pages that go one level
  // deeper (Stored Protocols, when a specific saved result is open) call
  // setBreadcrumb() to append that.
  function setBreadcrumb(items) {
    const container = document.getElementById('appBreadcrumb');
    if (!container) return;
    container.innerHTML = '';
    container.setAttribute('aria-label', 'Breadcrumb');
    items.forEach((item, i) => {
      if (i > 0) container.appendChild(el('span', { class: 'crumb-sep', 'aria-hidden': 'true' }, ['/']));
      if (item.href) {
        container.appendChild(el('a', { href: item.href }, [item.label]));
      } else {
        container.appendChild(el('span', { class: 'crumb-current', 'aria-current': 'page' }, [item.label]));
      }
    });
  }

  async function init(activePage, pageTitle) {
    let user;
    try {
      const res = await fetch('/api/auth/me', { credentials: 'include' });
      if (!res.ok) throw new Error('not signed in');
      user = await res.json();
    } catch (e) {
      window.location.href = '/site/signin.html';
      return null;
    }
    renderSidebar(activePage);
    renderTopbar(pageTitle, user);
    const navItem = NAV_ITEMS.find(n => n.id === activePage);
    setBreadcrumb([{ label: navItem ? navItem.label : pageTitle }]);
    document.title = pageTitle + ', Verilab';
    return user;
  }

  return { init, signOut, el, setBreadcrumb };
})();
