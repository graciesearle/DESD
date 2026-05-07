/*
handles:
    1. Category Carousel
    2. AJAX Filtering (fetching products without page reload)
    3. Template-based rendering 
*/

document.addEventListener('DOMContentLoaded', () => {
        // DOM elements
        const carousel = document.querySelector('.carousel');
        const leftBtn = document.querySelector('.carousel-btn.left');
        const rightBtn = document.querySelector('.carousel-btn.right');
        const grid = document.querySelector('.product-grid');

        const categoryLinks = document.querySelectorAll('.category-card, .sidebar ul li a');
        const searchForm = document.getElementById('search-form');
        const sidebarForm = document.getElementById('sidebar-form');
        const searchInput = document.getElementById('search-input');
        const searchTypeInput = document.getElementById('search-type-value');
        const organicFilter = document.getElementById('organic-filter');
        const allergenMode = document.getElementById('allergen-mode');
        const allergenQuery = document.getElementById('allergen-query');
        const surplusFilter = document.getElementById('surplus-filter');

        // Carousel Logic
        if (carousel && leftBtn && rightBtn) {
            // Function that checks scroll position and toggle buttons.
            const updateArrows = () => {
                // Hide left arrow if at the start.
                if (carousel.scrollLeft <= 10) {
                    leftBtn.style.display = 'none';
                } else {
                    leftBtn.style.display = 'flex';
                }
                
                // Hide right arrow if at the end. (current scroll position + visible width of carousel >= total scrollable width - 10.) 10 as sometimes browser has rounding issues.
                if (carousel.scrollLeft + carousel.clientWidth >= carousel.scrollWidth - 10) {
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

        // Keep track of the active category
        let currentCategory = new URLSearchParams(window.location.search).get('category') || '';

        function fetchFilteredProducts() {
            // hide suggestions when search form submitted
            if (dropdown) dropdown.style.display = 'none';

            const apiParams = new URLSearchParams();
            const q = searchInput ? searchInput.value.trim() : '';
            const searchType = searchTypeInput ? searchTypeInput.value : 'products';
            const organic = organicFilter ? organicFilter.value : '';
            const aMode = allergenMode ? allergenMode.value : '';
            const aQuery = allergenQuery ? allergenQuery.value : '';
            const surplus = (surplusFilter && surplusFilter.checked) ? 'true': '';

            // Build parameters
            if (currentCategory) apiParams.set('category', currentCategory);
            if (q) apiParams.set('q', q);
            if (searchType && searchType !== 'products') apiParams.set('search_type', searchType);
            if (organic) apiParams.set('organic', organic);
            if (aQuery) {
                apiParams.set('allergen_mode', aMode);
                apiParams.set('allergen', aQuery);
            }
            if (surplus === 'true') apiParams.set('surplus', 'true');

            // Update browser URL to reflect current filter state
            const queryString = apiParams.toString();
            const newUrl = window.location.pathname + (queryString ? '?' + queryString : '');
            history.pushState(null, '', newUrl);

            // update "clear filters"
            const clearBtn = document.getElementById('clear-filters-btn');
            if (clearBtn) {
                // show button if sidebar filter is active
                const isFilterActive = !!(organic || aQuery || (aMode === 'contains') || surplus === 'true');
                clearBtn.style.display = isFilterActive ? 'block' : 'none';
                
                // Update link so it keeps category and search
                const clearParams = new URLSearchParams();
                if (currentCategory) clearParams.set('category', currentCategory);
                if (q) clearParams.set('q', q);
                if (searchType && searchType !== 'products') clearParams.set('search_type', searchType);

                const clearBase = window.location.pathname;
                const clearQuery = clearParams.toString();
                clearBtn.href = clearBase + (clearQuery ? '?' + clearQuery : '');
            }

            // Fetch partials from Django
            fetch(newUrl, { headers: {'X-Requested-With': 'XMLHttpRequest'} })
                .then(response => response.text())
                .then(html => {
                    grid.innerHTML = html;
                })
                .catch(error => {
                    console.error('Error fetching data:', error);
                    grid.innerHTML = '<p>Failed to load products. Please try again later.</p>'
                });
        }

        // A. Submitting the search bar
        if (searchForm) {
            searchForm.addEventListener('submit', (e) => {
                e.preventDefault();
                fetchFilteredProducts();
            });
        }

        // B. Submitting the sidebar
        if (sidebarForm) {
            sidebarForm.addEventListener('submit', (e) => {
                e.preventDefault();
                fetchFilteredProducts();
            });
        }

        // C. Clicking a category link
        categoryLinks.forEach(link => {
            link.addEventListener('click', function(e) {
                e.preventDefault();

                // Get category from clicked link
                const href = this.getAttribute('href');
                const urlParams = new URLSearchParams(href.split('?')[1]);
                
                currentCategory = urlParams.get('category') || '';

                // Highlight selected category
                categoryLinks.forEach(l => l.classList.remove('active'));
                categoryLinks.forEach(l => {
                    const lHref = l.getAttribute('href');
                    const lParams = new URLSearchParams(lHref.split('?')[1]);
                    const lSlug = lParams.get('category') || '';
                    if (lSlug === currentCategory) {
                        l.classList.add('active');
                    } 
                });

                fetchFilteredProducts();
            });
        });
        
        // D. Clear Filters (make ajax instead of page reload)
        document.addEventListener('click', function(e) {
            const clearBtn = e.target.closest('#clear-filters-btn');
            if (clearBtn) {
                e.preventDefault();

                if (organicFilter) organicFilter.value = '';
                if (allergenMode) allergenMode.value = 'free';
                if (allergenQuery) allergenQuery.value = '';
                if (surplusFilter) surplusFilter.checked = false;

                fetchFilteredProducts();
            }
        });

        // E. Live Search Suggestions (filter-aware)
        const dropdown = document.getElementById('search-dropdown');
        let debounceTimer;

        if (searchInput && dropdown) {
            searchInput.addEventListener('input', function() {
                clearTimeout(debounceTimer);
                const query = searchInput.value.trim();

                if (query.length < 2) {
                    dropdown.style.display = 'none';
                    dropdown.innerHTML = '';
                    return;
                }

                // Debounce — wait 300ms after user stops typing
                debounceTimer = setTimeout(function() {
                    // get all current filters
                    const params = new URLSearchParams();
                    params.set('q', query)
                    params.set('search_type', searchTypeInput.value);

                    if (currentCategory) params.set('category', currentCategory);
                    if (organicFilter) params.set('organic', organicFilter.value);
                    if (allergenQuery.value) {
                        params.set('allergen', allergenQuery.value);
                        params.set('allergen_mode', allergenMode.value);
                    }
                    if (surplusFilter && surplusFilter.checked) params.set('surplus', 'true');

                    fetch(SUGGESTIONS_URL + '?' + params.toString())
                        .then(r => r.json())
                        .then(data => {
                            dropdown.innerHTML = '';
                            if (!data.results || data.results.length === 0) {
                                dropdown.innerHTML = '<div style="padding: 12px 16px; color: #888; font-size: 14px;">No matching items found with current filters</div>';
                                dropdown.style.display = 'block';
                                return;
                            }

                            data.results.forEach(function(item) {
                                const div = document.createElement('a');
                                div.href = item.url;
                                div.style.cssText = 'display:flex; align-items:center; gap:12px; padding:10px 14px; text-decoration:none; color:#333; border-bottom:1px solid #f0f0f0; cursor:pointer;';
                                div.onmouseover = function(){ this.style.backgroundColor = '#f9fafb'; };
                                div.onmouseout = function(){ this.style.backgroundColor = 'white'; };

                                div.innerHTML = `
                                    <img src="${item.image || DEFAULT_PRODUCT_IMAGE}" style="width:40px; height:40px; border-radius:4px; object-fit:cover; flex-shrink:0;">
                                    <div style="flex:1; min-width:0;">
                                    <div style="font-weight:600; font-size:14px;">${item.name}</div>
                                    <div style="font-size:12px; color:#888; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${item.description}</div>
                                    <div style="font-size:12px; color:#15803d; font-weight:bold;">£${item.price} / ${item.unit}</div>
                                    </div>
                                `;
                                dropdown.appendChild(div);
                            });
                            dropdown.style.display = 'block';
                        });
                }, 300);
            });

            // Close dropdown when clicking away
            document.addEventListener('click', (e) => {
                if (!searchInput.contains(e.target) && !dropdown.contains(e.target)){
                    dropdown.style.display = 'none';
                }
            });
        }
});