document.addEventListener("DOMContentLoaded", function () {
    const postcodeInput = document.getElementById("id_postcode");
    const addressSelect = document.getElementById("address-select");
    
    // Determine correct field (Customer vs Producer registration)
    const addressField = document.getElementById("id_delivery_address") || document.getElementById("id_address");

    if (!postcodeInput || !addressSelect || !addressField) return;

    let debounceTimer;

    postcodeInput.addEventListener("input", function () {
        const query = this.value.trim();
        if (query.length < 5) return;

        clearTimeout(debounceTimer);

        debounceTimer = setTimeout(() => {
            // Call API of the GoAddress Token to the browser 
            fetch(`/accounts/api/address-search/?q=${encodeURIComponent(query)}`)
                .then(res => res.json())
                .then(data => {
                    addressSelect.innerHTML = "";
                    addressSelect.classList.remove("hidden");

                    if (!data.results || data.results.length === 0) {
                        addressSelect.innerHTML = '<option disabled>No addresses found</option>';
                        return;
                    }

                    addressSelect.innerHTML = '<option disabled selected>Select your address...</option>';
                    data.results.forEach(item => {
                        const option = document.createElement("option");
                        option.value = item.address;
                        option.textContent = item.label;
                        addressSelect.appendChild(option);
                    });
                })
                .catch(err => console.error("Error fetching postcodes:", err));
        }, 500);
    });

    addressSelect.addEventListener("change", function () {
        const selected = this.value;

        fetch(`/accounts/api/address-search/?q=${encodeURIComponent(selected)}`)
        .then(res => res.json())
        .then(data => {
            if (!data.new_address_res || data.new_address_res.length === 0) return;

            const addr = data.new_address_res[0];
            const formatted = [
                addr.raw_address,
                addr.post_town,
                addr.county,
                addr.postcode
            ].filter(Boolean).join(", ");

            addressField.value = formatted;
            postcodeInput.value = addr.postcode;
        })
        .catch(err => console.error("Error fetching specific address:", err));
    });
});