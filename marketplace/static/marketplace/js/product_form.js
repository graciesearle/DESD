document.addEventListener("DOMContentLoaded", function() {
    // Find all radios that are part of the 'is_year_round' group.
    const allRadios = document.querySelectorAll('input[type="radio"]');
    const targetRadios = Array.from(allRadios).filter(r => r.name && r.name.includes("is_year_round"));

    const seasonFields = [
        document.querySelector('div[data-field="season_start_month"]'),
        document.querySelector('div[data-field="season_end_month"]')
    ];

    function toggleSeasonFields() {
        let isYearRound = true;
        
        // Find which radio is checked
        targetRadios.forEach(radio => {
            if (radio.checked) {
                // Determine if this radio corresponds to the 'Seasonal' selection.
                // Depending on Django's exact rendering, value might be 'False' or label text.
                if (radio.value === 'False' || radio.value === '0' || radio.value === 'false') {
                    isYearRound = false;
                }
            }
        });
        
        seasonFields.forEach(fieldWrapper => {
            if (!fieldWrapper) return;
            
            const selects = fieldWrapper.querySelectorAll('select');
            
            if (isYearRound) {
                // Dim wrapper and disable form inputs so they aren't bound in POST
                fieldWrapper.style.opacity = '0.4';
                fieldWrapper.style.pointerEvents = 'none';
                selects.forEach(select => {
                    select.disabled = true;
                });
            } else {
                // Restore opacity and re-enable bound form inputs
                fieldWrapper.style.opacity = '1';
                fieldWrapper.style.pointerEvents = 'auto';
                selects.forEach(select => {
                    select.disabled = false;
                });
            }
        });
    }

    if (targetRadios.length > 0) {
        targetRadios.forEach(radio => {
            radio.addEventListener('change', toggleSeasonFields);
        });
        
        toggleSeasonFields(); 
    }
});