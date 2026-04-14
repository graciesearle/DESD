
document.addEventListener("DOMContentLoaded", function() {
    const passwordInput = document.getElementById('id_password');
    const strengthContainer = document.getElementById('password-strength-container');
    const strengthBar = document.getElementById('password-strength-bar');
    const strengthLabel = document.getElementById('strength-label');

    if (passwordInput) {
        passwordInput.addEventListener('input', function() {
            const val = passwordInput.value;
            if (val.length > 0) {
                strengthContainer.classList.remove('hidden');
            } else {
                strengthContainer.classList.add('hidden');
            }

            let score = 0;
            // Length check
            if (val.length >= 8) score += 1;
            // Uppercase check
            if (/[A-Z]/.test(val)) score += 1;
            // Lowercase check
            if (/[a-z]/.test(val)) score += 1;
            // Number check
            if (/\d/.test(val)) score += 1;
            // Special character check
            if (/[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(val)) score += 1;

            // Update UI based on score
            if (score <= 2) {
                strengthBar.style.width = '33%';
                strengthBar.className = 'h-full transition-all duration-300 bg-red-500';
                strengthLabel.textContent = 'Weak';
                strengthLabel.className = 'text-red-500';
            } else if (score === 3 || score === 4) {
                strengthBar.style.width = '66%';
                strengthBar.className = 'h-full transition-all duration-300 bg-yellow-500';
                strengthLabel.textContent = 'Medium';
                strengthLabel.className = 'text-yellow-600';
            } else if (score === 5) {
                strengthBar.style.width = '100%';
                strengthBar.className = 'h-full transition-all duration-300 bg-green-500';
                strengthLabel.textContent = 'Strong';
                strengthLabel.className = 'text-green-600';
            }
        });
    }
});