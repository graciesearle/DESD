document.addEventListener('DOMContentLoaded', () => {
        const carousel = document.querySelector('.carousel');
        const leftBtn = document.querySelector('.carousel-btn.left');
        const rightBtn = document.querySelector('.carousel-btn.right');

        if (carousel && leftBtn && rightBtn) {
            // Function that checks scroll position and toggle buttons.
            const updateArrows = () => {
                // Hide left arrow if at the start.
                if (carousel.scrollLeft <= 5) {
                    leftBtn.style.display = 'none';
                } else {
                    leftBtn.style.display = 'flex';
                }
                
                // Hide right arrow if at the end. (current scroll position + visible width of carousel >= total scrollable width - 5.) 5 as sometimes browser has rounding issues.
                if (carousel.scrollLeft + carousel.clientWidth >= carousel.scrollWidth - 5) {
                    rightBtn.style.display = 'none';
                } else {
                    rightBtn.style.display = 'flex';
                }
            };

            // Throttle scroll event to stop lag
            let isTicking = false;
            carousel.addEventListener('scroll', () => {
                if (!isTicking) {
                    window.requestAnimationFrame(() => { // Only run check when it has free time to draw next frame.
                        updateArrows();
                        isTicking = false;
                    });
                    isTicking = true;
                }
            });

            // Attach click events (Scroll by exactly the visible width of the container)
            leftBtn.addEventListener('click', () => {
                let scrollAmount = carousel.clientWidth * 0.8; //scroll 80% of the screen, leaving a tiny bit of the next card as a hint.
                carousel.scrollBy({left: -scrollAmount, behavior: 'smooth'});
            });

            rightBtn.addEventListener('click', () => {
                let scrollAmount = carousel.clientWidth * 0.8;
                carousel.scrollBy({left: scrollAmount, behavior: 'smooth'});
            });

            // listen for windows resize
            window.addEventListener('resize', updateArrows);

            // Run once on load
            updateArrows();
        }
    });

    // API Filtering
    document.addEventListener('DOMContentLoaded', () => {
        const grid = document.querySelector('.product-grid');
        const template = document.getElementById('product-template');
        const categoryLinks = document.querySelectorAll('.category-card, .sidebar a'); // Target carousel and sidebar links

        categoryLinks.forEach(link => {
            link.addEventListener('click', function(e) {
                // Stop page from reloading
                e.preventDefault();

                // URL
                const href = this.getAttribute('href');
                const urlParams = new URLSearchParams(href.split('?')[1]);
                const categorySlug = urlParams.get('category') || '';

                // Highlight selected category
                categoryLinks.forEach(l => l.classList.remove('active'));
                this.classList.add('active');

                // Fetch data
                fetch(`/marketplace/api/products/?category=${categorySlug}`)
                    .then(response => response.json())
                    .then(data => {
                        grid.innerHTML = ''; // Clear products

                        if (data.length === 0) {
                            grid.innerHTML = '<p>No products found in this category</p>';
                            return;
                        }

                        // Loop through data and clone the template.
                        data.forEach(product => {
                            // clone template
                            const clone = template.content.cloneNode(true);

                            // Fill Basic info
                            const imgUrl = product.image ? product.image: DEFAULT_PRODUCT_IMAGE;
                            clone.querySelector('.p-image').src = imgUrl;
                            clone.querySelector('.p-image').alt = product.name;

                            clone.querySelector('.p-name').textContent = product.name;
                            
                            // Truncate desc
                            let desc = product.description || '';
                            if (desc.split(' ').length > 10) {
                                desc = desc.split(' ').slice(0, 10).join(' ') + '...';
                            }
                            clone.querySelector('.p-desc').textContent = desc;

                            // Price and Unit
                            const unit = product.unit ? product.unit : '';
                            const unitEl = clone.querySelector('.p-price-unit');

                            unitEl.textContent = '';
                            const strong = document.createElement('strong');
                            strong.textContent = `£${product.price}`;
                            unitEl.append(strong);

                            if (product.unit) {
                                unitEl.append(` / ${product.unit}`);
                            }

                            // Stock warning
                            if (product.stock_quantity < 10) {
                                const stockEl = clone.querySelector('.stock-warning');
                                stockEl.textContent = `Only ${product.stock_quantity} left!`;
                                stockEl.style.display = 'block';
                            }

                            // Allergens
                            if (product.allergen_names && product.allergen_names.length > 0) {
                                const allergenDiv = clone.querySelector('.allergens');
                                allergenDiv.style.display = 'flex'; // show it

                                product.allergen_names.forEach(allergen => {
                                    const span = document.createElement('span');
                                    span.className = 'allergen-tag';
                                    span.textContent = allergen; // name only
                                    allergenDiv.appendChild(span);
                                });
                            }

                            // Seasonality
                            if (product.season_end) {
                                const seasonEl = clone.querySelector('.seasonal-info');
                                seasonEl.textContent = `Season ends: ${product.season_end}`;
                                seasonEl.style.display = 'inline-block';
                            }

                            // Producer name
                            clone.querySelector('.producer-name').textContent = product.producer || 'Unknown';

                            // Add finished card to grid
                            grid.appendChild(clone);
                        });
                    })
                    .catch(error => {
                        console.error('Error fetching data:', error);
                        grid.innerHTML = '<p>Failed to load products. Please try again later.</p>'
                    });
            });
        });
    });