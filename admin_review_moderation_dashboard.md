# Admin Review & Moderation Dashboard Implementation Plan

Admins require a dedicated interface to manage user-generated content, specifically customer reviews and producer responses. This page should be accessible via the main admin navigation bar.

## 1. Core Objectives
*   **Safety & Quality**: Maintain a safe community by moderating inappropriate content.
*   **Transparency**: Allow admins to oversee the dialogue between customers and producers.
*   **Efficiency**: Provide tools for high-volume moderation (bulk actions, filters, search).
*   **Auditability**: Maintain a strict history of who moderated what and when.

## 2. Moderation Policy & State Management

### Pre-Moderation vs. Post-Moderation
The system will operate on a **Pre-Moderation** policy to reduce friction for users. 
*   Reviews and Producer Responses are live immediately upon submission.
*   The `Pending` status in the admin dashboard indicates "Requires Admin Triage," not "Hidden from Public."
*   Admins step in to transition states to `Approved` (verified safe) or `Rejected` (pulled from public view).

### The "Re-Trigger" Rule
To prevent bad actors from bypassing moderation:
*   Whenever a producer creates or edits their `producer_response`, the system must automatically reset the `response_moderation_status` back to `Pending`, moving it back to the top of the admin queue.

## 3. UI/UX Design

### The "Action Required" Default View
By default, the dashboard should not just show "All Reviews". It should default to an **Action Required** queue that aggregates:
1.  Unmoderated (`Pending`) Customer Reviews.
2.  Unmoderated (`Pending`) Producer Responses.

### Review Table Columns
*   **Product**: Image thumbnail + Name (Handle soft-deleted products gracefully with an "Archived Product" badge).
*   **Reviewer**: Display name + Role badge. If `is_anonymous` is true, show the real name to the admin but include a "🛡️ Posted Anonymously" badge.
*   **Review Details**: Rating (stars) + Snippet of text.
*   **Producer Reply**: Indicator icon (e.g., 💬) if a producer has responded.
*   **Date**: Submission timestamp.
*   **Actions**: Quick buttons for Approve/Reject/View.

### Detailed View (Modal)
Clicking any row opens a modal containing:
*   **Full Context**: The complete review text and all metadata, plus direct links to the live Product Page and Producer Profile.
*   **Response Management**: View and moderate the producer's response independently of the review.
*   **Admin Tools**: Field to enter a moderation reason and buttons to change status.
*   **Audit History Tab**: A view tapping into the `HistoricalRecords` table to show the history of edits and moderations for this specific review.

### Bulk Actions & Filtering
*   **Bulk Select**: Select multiple rows to "Approve All" or "Hide All" in one click.
*   **Filtering**: Filter by User Type (Role), Producer, and Moderation Status.
*   **Search**: Keyword search across review titles, bodies, and producer response text.

## 4. Technical Architecture & Database Changes

### Model Updates (`products/models.py`)
To support independent moderation without data loss, the `Review` model must be migrated from a boolean `is_visible` flag to explicit status fields.

**New/Updated Fields Required:**
```python
class ModerationStatus(models.TextChoices):
    PENDING = 'PENDING', 'Pending Review'
    APPROVED = 'APPROVED', 'Approved'
    REJECTED = 'REJECTED', 'Rejected/Hidden'

# Replacing is_visible
moderation_status = models.CharField(
    max_length=20, 
    choices=ModerationStatus.choices, 
    default=ModerationStatus.PENDING
)

# New fields for independent response moderation
response_moderation_status = models.CharField(
    max_length=20, 
    choices=ModerationStatus.choices, 
    default=ModerationStatus.PENDING
)
response_moderated_by = models.ForeignKey(
    settings.AUTH_USER_MODEL, 
    on_delete=models.SET_NULL, 
    null=True, blank=True, 
    related_name="moderated_responses"
)
response_moderated_at = models.DateTimeField(null=True, blank=True)
```

### Migrations
*   A data migration script must be written to map existing `is_visible=True` reviews to `moderation_status=APPROVED`, and `is_visible=False` to `REJECTED`.

### Component Modularity
*   The UI must be decoupled from the data source. Use a generic "Moderation Row" component that can be extended to support reviews for **Community Content** (Recipes, Educational Posts) when those models are added in the future.
*   Styling should utilize the project's existing Tailwind CSS system to ensure aesthetic consistency with the `admin_commissions` dashboard.
