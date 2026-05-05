document.addEventListener("DOMContentLoaded", function() {
    const form = document.getElementById("draft-review-form");
    const qtyInputs = document.querySelectorAll(".qty-input");
    const spinner = document.getElementById("ajax-spinner");
    const messagesContainer = document.getElementById("js-messages-container");
    let timeout = null;

    qtyInputs.forEach(input => {
        input.addEventListener("input", function() {
            clearTimeout(timeout);
            timeout = setTimeout(() => {
                updateCartTotals();
            }, 300); 
        });
    });

    function updateCartTotals() {
        spinner.classList.remove('opacity-0'); // Show loading spinner
        
        const formData = new FormData(form);
        formData.append("action", "update_quantities");

        fetch(window.location.href, {
            method: 'POST',
            body: formData,
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => response.json())
        .then(data => {
            // If order was emptied, redirect safely
            if (data.redirect) {
                window.location.href = data.redirect;
                return;
            }

            // Update Global Totals
            document.getElementById('order-subtotal').innerText = '£' + data.order_subtotal;
            document.getElementById('order-commission').innerText = '£' + data.order_commission;
            
            const totalEl = document.getElementById('order-total');
            totalEl.innerText = '£' + data.order_total;
            // Flash green color to show it updated
            totalEl.classList.add('text-green-500');
            setTimeout(() => totalEl.classList.remove('text-green-500'), 500);

            // Update Individual Line Items & Check for server-enforced stock caps
            for (const [itemId, itemData] of Object.entries(data.items)) {
                const lineTotalEl = document.getElementById('line-total-' + itemId);
                if (lineTotalEl) lineTotalEl.innerText = '£' + itemData.line_total;
                
                const inputEl = form.querySelector(`input[name="item_qty_${itemId}"]`);
                if (inputEl && inputEl.value !== itemData.qty.toString()) {
                    inputEl.value = itemData.qty; // Server capped the quantity based on stock
                }
            }

            // Update Sub-order totals
            for (const [subId, subData] of Object.entries(data.sub_orders)) {
                const subEl = document.getElementById('subtotal-' + subId);
                if (subEl) subEl.innerText = '£' + subData.subtotal;
            }

            // Show stock warnings dynamically if they exist
            messagesContainer.innerHTML = "";
            data.warnings.forEach(msg => {
                messagesContainer.innerHTML += `
                <div class="flex items-start gap-3 p-4 rounded-lg border bg-amber-50 border-amber-300 text-amber-800 shadow-sm animate-pulse">
                    <p class="text-sm font-bold">${msg}</p>
                </div>`;
            });
            
        })
        .catch(error => console.error("Error updating cart:", error))
        .finally(() => {
            spinner.classList.add('opacity-0'); // Hide spinner
        });
    }
});