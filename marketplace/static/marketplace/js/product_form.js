document.addEventListener("DOMContentLoaded", function() {
    // Django automatically assigns the 'id_' prefix to form fields
    const yearRoundCheckbox = document.getElementById('id_is_year_round');
    const seasonStartInput = document.getElementById('id_season_start');
    const seasonEndInput = document.getElementById('id_season_end');

    function toggleSeasonFields() {
        if (!yearRoundCheckbox) return;
        
        if (yearRoundCheckbox.checked) {
            // Clear and disable date inputs to prevent accidental data entry
            if (seasonStartInput) {
                seasonStartInput.value = '';
                seasonStartInput.disabled = true;
                seasonStartInput.closest('div').style.opacity = '0.5';
            }
            if (seasonEndInput) {
                seasonEndInput.value = '';
                seasonEndInput.disabled = true;
                seasonEndInput.closest('div').style.opacity = '0.5';
            }
        } else {
            // Re-enable inputs
            if (seasonStartInput) {
                seasonStartInput.disabled = false;
                seasonStartInput.closest('div').style.opacity = '1';
            }
            if (seasonEndInput) {
                seasonEndInput.disabled = false;
                seasonEndInput.closest('div').style.opacity = '1';
            }
        }
    }

    if (yearRoundCheckbox) {
        // Listen for user clicks
        yearRoundCheckbox.addEventListener('change', toggleSeasonFields);
        
        // Run immediately on page load (important for Edit Product page)
        toggleSeasonFields(); 
    }
});