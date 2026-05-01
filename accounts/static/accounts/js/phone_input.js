// To follow DRY as this is used in 3 places as of the moment this is created.

document.addEventListener("DOMContentLoaded", function() {
    // Select any input that might be a phone number
    const phoneInputs = document.querySelectorAll("#id_phone, input[type='tel']");
    
    phoneInputs.forEach(phoneInput => {
        const iti = window.intlTelInput(phoneInput, {
            initialCountry: "gb",
            separateDialCode: true,
            utilsScript: "https://cdnjs.cloudflare.com/ajax/libs/intl-tel-input/17.0.8/js/utils.js",
        });

        // Insert the full dial code on submission
        const form = phoneInput.closest("form");
        if (form) {
            form.addEventListener("submit", function () {
                const fullNumber = iti.getNumber();
                if (fullNumber) {
                    phoneInput.value = fullNumber;
                }
            });
        }
    });
});