/**
 * cart.js — AJAX interactions for the cart detail page.
 *
 * Handles +/- quantity, remove item, and keeps the order summary
 * and nav-bar counter in sync without page reloads.
 */

(function () {
    'use strict';

    // ---- Helpers ----

    /** Read the CSRF token from the meta tag (works with CSRF_COOKIE_HTTPONLY). */
    function getCSRFToken() {
        var meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    /** Show a brief toast message at the bottom-right. */
    function showToast(message, durationMs) {
        durationMs = durationMs || 2500;
        var toast = document.getElementById('cart-toast');
        var span  = document.getElementById('cart-toast-message');
        if (!toast || !span) return;
        span.textContent = message;
        toast.classList.remove('hidden');
        clearTimeout(toast._timer);
        toast._timer = setTimeout(function () {
            toast.classList.add('hidden');
        }, durationMs);
    }

    /** Update every [data-cart-count] badge in the page (nav bar). */
    function updateNavCounter(count) {
        document.querySelectorAll('[data-cart-count]').forEach(function (el) {
            el.textContent = count;
            if (count > 0) {
                el.classList.remove('hidden');
                el.style.display = 'flex';
            } else {
                el.classList.add('hidden');
                el.style.display = 'none';
            }
        });
    }

    /** Generic fetch wrapper that includes CSRF & JSON headers. */
    function cartFetch(url, method, body) {
        var opts = {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCSRFToken(),
            },
            credentials: 'same-origin',
        };
        if (body) opts.body = JSON.stringify(body);
        return fetch(url, opts).then(function (res) {
            return res.json().then(function (data) {
                return { ok: res.ok, status: res.status, data: data };
            });
        });
    }

    // ---- DOM update helpers ----

    function updateSummary(data) {
        var el;
        el = document.querySelector('[data-display="grand-total"]');
        if (el && data.grand_total) el.textContent = '£' + data.grand_total;

        // Producer subtotals
        if (data.producer_subtotals) {
            Object.keys(data.producer_subtotals).forEach(function (name) {
                var pEl = document.querySelector('[data-producer-subtotal="' + name + '"]');
                if (pEl) {
                    var span = pEl.querySelector('span:last-child');
                    if (span) span.textContent = '£' + data.producer_subtotals[name];
                }
            });
        }

        if (typeof data.cart_total_items !== 'undefined') {
            updateNavCounter(data.cart_total_items);
        }
    }

    /** If a producer group has no items left, remove the whole card. */
    function cleanEmptyGroups() {
        document.querySelectorAll('[data-producer-group]').forEach(function (group) {
            if (group.querySelectorAll('[data-item-row]').length === 0) {
                group.remove();
            }
        });
        // If no items at all, reload to show the empty-cart state
        if (document.querySelectorAll('[data-item-row]').length === 0) {
            window.location.reload();
        }
    }

    // ---- Event delegation ----

    document.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-action]');
        if (!btn) return;

        var action = btn.getAttribute('data-action');
        var row = btn.closest('[data-item-row]');

        if (!row && action !== 'checkout') return;

        var itemId      = row ? row.getAttribute('data-item-id') : null;
        var qtyInput    = row ? row.querySelector('[data-input="quantity"]') : null;
        var currentQty  = qtyInput ? parseInt(qtyInput.value, 10) : 0;
        var stock       = row ? parseInt(row.getAttribute('data-stock'), 10) : 0;
        var unitPrice   = row ? parseFloat(row.getAttribute('data-unit-price')) : 0;

        // --- Decrease ---
        if (action === 'decrease-qty') {
            var newQty = currentQty - 1;
            if (newQty < 1) return;

            cartFetch('/cart/api/update/' + itemId + '/', 'PATCH', { quantity: newQty })
                .then(function (res) {
                    if (!res.ok) { showToast(res.data.error || 'Error', 3000); return; }
                    qtyInput.value = res.data.quantity;
                    row.querySelector('[data-display="item-total"]').textContent = '£' + res.data.item_total;
                    updateSummary(res.data);
                });
        }

        // --- Increase ---
        else if (action === 'increase-qty') {
            var newQty = currentQty + 1;
            if (newQty > stock) {
                showToast('Only ' + stock + ' in stock.', 2500);
                return;
            }

            cartFetch('/cart/api/update/' + itemId + '/', 'PATCH', { quantity: newQty })
                .then(function (res) {
                    if (!res.ok) { showToast(res.data.error || 'Error', 3000); return; }
                    qtyInput.value = res.data.quantity;
                    row.querySelector('[data-display="item-total"]').textContent = '£' + res.data.item_total;
                    updateSummary(res.data);
                });
        }

        // --- Remove ---
        else if (action === 'remove-item') {
            cartFetch('/cart/api/remove/' + itemId + '/', 'DELETE')
                .then(function (res) {
                    if (!res.ok) { showToast(res.data.error || 'Error', 3000); return; }
                    row.remove();
                    updateSummary(res.data);
                    cleanEmptyGroups();
                    showToast('Item removed.');
                });
        }
    });

    // ---- Manual quantity input (on blur / Enter) ----

    document.addEventListener('change', function (e) {
        if (!e.target.matches('[data-input="quantity"]')) return;

        var input = e.target;
        var row   = input.closest('[data-item-row]');
        var itemId = row.getAttribute('data-item-id');
        var newQty = parseInt(input.value, 10);
        var stock  = parseInt(row.getAttribute('data-stock'), 10);

        if (isNaN(newQty) || newQty < 1) { newQty = 1; input.value = 1; }
        if (newQty > stock) { newQty = stock; input.value = stock; showToast('Only ' + stock + ' in stock.'); }

        cartFetch('/cart/api/update/' + itemId + '/', 'PATCH', { quantity: newQty })
            .then(function (res) {
                if (!res.ok) { showToast(res.data.error || 'Error', 3000); return; }
                input.value = res.data.quantity;
                row.querySelector('[data-display="item-total"]').textContent = '£' + res.data.item_total;
                updateSummary(res.data);
            });
    });

})();
