(() => {
  'use strict';
  
  function getElements() {
    const drawer = document.getElementById('mobileNavDrawer') || document.getElementById('universalDashboardDrawer');
    const backdrop = document.getElementById('mobileDrawerBackdrop') || document.getElementById('universalDashboardBackdrop');
    const toggleBtn = document.getElementById('mobileMenuToggleBtn');
    return { drawer, backdrop, toggleBtn };
  }

  let isOpen = false;
  let previousActiveElement = null;

  function getFocusableElements(container) {
    if (!container) return [];
    return [...container.querySelectorAll(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )].filter(el => el.getClientRects().length > 0 && !el.closest('[hidden]'));
  }

  function openDrawer() {
    const { drawer, backdrop, toggleBtn } = getElements();
    if (!drawer || isOpen) return;

    isOpen = true;
    previousActiveElement = document.activeElement;

    // Toggle class on body (never set inline overflow styles)
    document.body.classList.add('drawer-open');

    // Drawer state
    drawer.inert = false;
    drawer.setAttribute('aria-hidden', 'false');
    drawer.classList.add('active');

    // Backdrop state
    if (backdrop) {
      backdrop.setAttribute('aria-hidden', 'false');
      backdrop.classList.add('active');
    }

    // Toggle button state
    if (toggleBtn) {
      toggleBtn.classList.add('active');
      toggleBtn.setAttribute('aria-expanded', 'true');
    }

    const allTriggers = document.querySelectorAll(
      '[onclick*="toggleMobileNavDrawer"], [onclick*="toggleUniversalDashboard"], #mobileMenuToggleBtn'
    );
    allTriggers.forEach(t => t.setAttribute('aria-expanded', 'true'));

    // Focus first element in drawer
    const focusable = getFocusableElements(drawer);
    if (focusable.length > 0) {
      focusable[0].focus({ preventScroll: true });
    }
  }

  function closeDrawer() {
    const { drawer, backdrop, toggleBtn } = getElements();
    if (!drawer) return;

    isOpen = false;

    // Drawer state
    drawer.classList.remove('active');
    drawer.inert = true;
    drawer.setAttribute('aria-hidden', 'true');

    // Backdrop state
    if (backdrop) {
      backdrop.classList.remove('active');
      backdrop.setAttribute('aria-hidden', 'true');
    }

    // Remove class from body (never set inline overflow styles)
    document.body.classList.remove('drawer-open');

    // Toggle button state
    if (toggleBtn) {
      toggleBtn.classList.remove('active');
      toggleBtn.setAttribute('aria-expanded', 'false');
    }

    const allTriggers = document.querySelectorAll(
      '[onclick*="toggleMobileNavDrawer"], [onclick*="toggleUniversalDashboard"], #mobileMenuToggleBtn'
    );
    allTriggers.forEach(t => t.setAttribute('aria-expanded', 'false'));

    // Restore focus
    if (previousActiveElement && previousActiveElement.isConnected) {
      try {
        previousActiveElement.focus({ preventScroll: true });
      } catch (e) {
        // Ignore focus error if element is not focusable anymore
      }
    }
  }

  function toggleDrawer() {
    const { drawer } = getElements();
    if (!drawer) return;
    if (drawer.classList.contains('active') || isOpen) {
      closeDrawer();
    } else {
      openDrawer();
    }
  }

  // Expose global controller functions
  window.toggleMobileNavDrawer = toggleDrawer;
  window.closeMobileNavDrawer = closeDrawer;
  window.toggleUniversalDashboard = toggleDrawer;
  window.closeUniversalDashboard = closeDrawer;

  // Escape key and Tab focus trap listeners
  document.addEventListener('keydown', event => {
    const { drawer } = getElements();
    if (!drawer || (!isOpen && !drawer.classList.contains('active'))) return;

    if (event.key === 'Escape') {
      event.preventDefault();
      closeDrawer();
      return;
    }

    if (event.key === 'Tab') {
      const focusable = getFocusableElements(drawer);
      if (!focusable.length) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];

      if (event.shiftKey && (document.activeElement === first || !drawer.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !drawer.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    }
  });

  // Attach backdrop click listener if present
  document.addEventListener('DOMContentLoaded', () => {
    const backdrop = document.getElementById('mobileDrawerBackdrop') || document.getElementById('universalDashboardBackdrop');
    if (backdrop) {
      backdrop.addEventListener('click', closeDrawer);
    }
  });
})();
