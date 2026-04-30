document.addEventListener("DOMContentLoaded", function() {
    const buttons = document.querySelectorAll('.tab-btn');
    const contents = document.querySelectorAll('.tab-content');
    
    if (buttons.length === 0 || contents.length === 0) return;

    // Check for 'tab' in URL params to persist state after a form submission
    const urlParams = new URLSearchParams(window.location.search);
    let activeTab = urlParams.get('tab') || 'account';

    function switchTab(targetId) {
        contents.forEach(c => c.classList.add('hidden'));
        
        buttons.forEach(b => {
            b.classList.remove('bg-green-50', 'text-green-700');
            if(!b.classList.contains('text-red-600')) {
                b.classList.add('text-gray-600');
            }
        });

        const targetContent = document.getElementById(targetId);
        if(targetContent) {
            targetContent.classList.remove('hidden');
            
            // Highlight active button
            const activeButton = document.querySelector(`button[data-target="${targetId}"]`);
            if(activeButton) {
                activeButton.classList.add('bg-green-50', 'text-green-700');
                activeButton.classList.remove('text-gray-600');
            }
            // Update URL parameter so refreshing stays on the same tab
            const newUrl = window.location.pathname + '?tab=' + targetId;
            window.history.replaceState({path:newUrl}, '', newUrl);
        }
    }

    switchTab(activeTab);

    // Add click listeners to sidebar buttons
    buttons.forEach(btn => {
        btn.addEventListener('click', function() {
            switchTab(this.dataset.target);
        });
    });
});