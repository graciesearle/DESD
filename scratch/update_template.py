import re

with open("marketplace/templates/marketplace/admin_review_moderation.html", "r", encoding="utf-8") as f:
    content = f.read()

# Update for loop and table body
new_tbody = """<tbody class="divide-y divide-gray-100">
                    {% for item in items %}
                    <tr class="hover:bg-gray-50 transition cursor-pointer" data-review-row="{{ item.id }}" data-item-type="{{ item.item_type }}">
                        <!-- Checkbox -->
                        <td class="px-4 py-3" onclick="event.stopPropagation();">
                            <input type="checkbox" name="item_ids" value="{{ item.item_type }}_{{ item.id }}" class="review-checkbox rounded border-gray-300 text-green-600 focus:ring-green-500">
                        </td>

                        <!-- Target (Product / Post / Recipe) -->
                        <td class="px-4 py-3">
                            <div class="flex items-center gap-3">
                                {% if item.item_type == 'review' %}
                                    {% if item.product and item.product.image %}
                                        <img src="{{ item.product.image.url }}" alt="" class="w-10 h-10 rounded-lg object-cover border border-gray-200 flex-shrink-0">
                                    {% else %}
                                        <div class="w-10 h-10 rounded-lg bg-gray-100 border border-gray-200 flex items-center justify-center text-gray-400 text-xs flex-shrink-0">N/A</div>
                                    {% endif %}
                                    <div>
                                        {% if item.product and not item.product.is_deleted %}
                                            <p class="text-sm font-semibold text-gray-800 truncate max-w-[140px]">{{ item.product.name }}</p>
                                        {% else %}
                                            <p class="text-sm font-semibold text-gray-400 italic">Archived Product</p>
                                        {% endif %}
                                    </div>
                                {% else %}
                                    {% if item.post and item.post.image %}
                                        <img src="{{ item.post.image.url }}" alt="" class="w-10 h-10 rounded-lg object-cover border border-gray-200 flex-shrink-0">
                                    {% elif item.recipe and item.recipe.image %}
                                        <img src="{{ item.recipe.image.url }}" alt="" class="w-10 h-10 rounded-lg object-cover border border-gray-200 flex-shrink-0">
                                    {% else %}
                                        <div class="w-10 h-10 rounded-lg bg-gray-100 border border-gray-200 flex items-center justify-center text-gray-400 text-xs flex-shrink-0">N/A</div>
                                    {% endif %}
                                    <div>
                                        {% if item.post %}
                                            <p class="text-sm font-semibold text-blue-800 truncate max-w-[140px]">Post: {{ item.post.title }}</p>
                                        {% elif item.recipe %}
                                            <p class="text-sm font-semibold text-purple-800 truncate max-w-[140px]">Recipe: {{ item.recipe.title }}</p>
                                        {% else %}
                                            <p class="text-sm font-semibold text-gray-400 italic">Unknown Target</p>
                                        {% endif %}
                                    </div>
                                {% endif %}
                            </div>
                        </td>

                        <!-- Reviewer/Author -->
                        <td class="px-4 py-3">
                            {% if item.item_type == 'review' %}
                                <p class="text-sm font-semibold text-gray-800">{{ item.reviewer_real_name }}</p>
                                <div class="flex items-center gap-1.5 mt-0.5">
                                    <span class="text-xs text-gray-500">{{ item.customer.get_role_display }}</span>
                                    {% if item.is_anonymous %}
                                        <span class="text-xs font-bold text-indigo-600" title="This review is posted anonymously to customers">🛡️ Anon</span>
                                    {% endif %}
                                </div>
                            {% else %}
                                <p class="text-sm font-semibold text-gray-800">{{ item.author.email }}</p>
                                <div class="flex items-center gap-1.5 mt-0.5">
                                    <span class="text-xs text-gray-500">{{ item.author.get_role_display }}</span>
                                    <span class="text-xs font-bold text-blue-600">💬 Comment</span>
                                </div>
                            {% endif %}
                        </td>

                        <!-- Content details -->
                        <td class="px-4 py-3 max-w-[260px]">
                            <div class="flex items-center gap-1 mb-1">
                                {% if item.item_type == 'review' %}
                                    <span class="text-amber-500 text-sm" aria-label="{{ item.rating }} out of 5 stars">
                                        {% for _ in "12345" %}{% if forloop.counter <= item.rating %}&#9733;{% else %}&#9734;{% endif %}{% endfor %}
                                    </span>
                                {% endif %}
                                <!-- Status badge -->
                                {% if item.moderation_status == 'PENDING' %}
                                    <span class="ml-2 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800 border border-amber-200">Pending</span>
                                {% elif item.moderation_status == 'APPROVED' %}
                                    <span class="ml-2 px-2 py-0.5 rounded-full text-[10px] font-bold bg-green-100 text-green-800 border border-green-200">Approved</span>
                                {% elif item.moderation_status == 'REJECTED' %}
                                    <span class="ml-2 px-2 py-0.5 rounded-full text-[10px] font-bold bg-red-100 text-red-800 border border-red-200">Rejected</span>
                                {% endif %}
                            </div>
                            {% if item.item_type == 'review' %}
                                <p class="text-sm font-semibold text-gray-800 truncate">{{ item.title }}</p>
                            {% else %}
                                <p class="text-sm font-semibold text-gray-800 truncate">Community Comment</p>
                            {% endif %}
                            <p class="text-xs text-gray-500 truncate">{{ item.body|truncatewords:12 }}</p>
                        </td>

                        <!-- Reply indicator -->
                        <td class="px-4 py-3 text-center">
                            {% if item.item_type == 'review' %}
                                {% if item.producer_response %}
                                    <span title="Producer has responded" class="text-lg">💬</span>
                                    {% if item.response_moderation_status == 'PENDING' %}
                                        <span class="block text-[10px] font-bold text-amber-700 mt-0.5">Pending</span>
                                    {% elif item.response_moderation_status == 'REJECTED' %}
                                        <span class="block text-[10px] font-bold text-red-700 mt-0.5">Rejected</span>
                                    {% endif %}
                                {% else %}
                                    <span class="text-gray-300">—</span>
                                {% endif %}
                            {% else %}
                                {% if item.is_reply %}
                                    <span title="Producer reply to comment" class="text-lg">💬</span>
                                {% else %}
                                    <span class="text-gray-300">—</span>
                                {% endif %}
                            {% endif %}
                        </td>

                        <!-- Date -->
                        <td class="px-4 py-3 whitespace-nowrap text-sm text-gray-500">
                            {{ item.created_at|date:"d M Y" }}
                        </td>

                        <!-- Quick actions -->
                        <td class="px-4 py-3 text-center" onclick="event.stopPropagation();">
                            <div class="flex items-center justify-center gap-1">
                                {% if item.moderation_status != 'APPROVED' %}
                                <form method="post" action="{% if item.item_type == 'review' %}{% url 'marketplace:admin_moderate_review' item.id %}{% else %}{% url 'marketplace:admin_moderate_comment' item.id %}{% endif %}">
                                    {% csrf_token %}
                                    <input type="hidden" name="action" value="approve">
                                    <button type="submit" class="px-2 py-1 rounded-md bg-green-100 text-green-800 text-xs font-bold hover:bg-green-200 transition" title="Approve">✓</button>
                                </form>
                                {% endif %}
                                {% if item.moderation_status != 'REJECTED' %}
                                <form method="post" action="{% if item.item_type == 'review' %}{% url 'marketplace:admin_moderate_review' item.id %}{% else %}{% url 'marketplace:admin_moderate_comment' item.id %}{% endif %}">
                                    {% csrf_token %}
                                    <input type="hidden" name="action" value="reject">
                                    <button type="submit" class="px-2 py-1 rounded-md bg-red-100 text-red-800 text-xs font-bold hover:bg-red-200 transition" title="Reject">✕</button>
                                </form>
                                {% endif %}
                                <button type="button" class="px-2 py-1 rounded-md bg-gray-100 text-gray-700 text-xs font-bold hover:bg-gray-200 transition" onclick="openReviewModal({{ item.id }}, '{{ item.item_type }}')" title="View details">👁</button>
                            </div>
                        </td>
                    </tr>
                    {% empty %}
                    <tr>
                        <td colspan="7" class="px-6 py-12 text-center">
                            <p class="text-gray-500 text-sm font-medium">
                                {% if status_filter == 'action_required' %}
                                    🎉 No items need attention right now.
                                {% else %}
                                    No items found matching your filters.
                                {% endif %}
                            </p>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>"""

content = re.sub(
    r'<tbody class="divide-y divide-gray-100">.*?</tbody>',
    new_tbody,
    content,
    flags=re.DOTALL
)

# Update openReviewModal signature in JS
content = content.replace("openReviewModal(row.getAttribute('data-review-row'));", 
                        "openReviewModal(row.getAttribute('data-review-row'), row.getAttribute('data-item-type'));")

content = content.replace("window.openReviewModal = function (reviewId) {", 
                        "window.openReviewModal = function (reviewId, itemType) {")

content = content.replace("fetch(\"{% url 'marketplace:admin_review_moderation' %}\".replace(/\\/$/, '') + '/' + reviewId + '/detail/')",
                        "fetch(\"{% url 'marketplace:admin_review_moderation' %}\".replace(/\\/$/, '') + '/' + reviewId + '/detail/?type=' + itemType)")

# Update checkboxes to use item_ids
content = content.replace("name=\"review_ids\"", "name=\"item_ids\"")

with open("marketplace/templates/marketplace/admin_review_moderation.html", "w", encoding="utf-8") as f:
    f.write(content)
