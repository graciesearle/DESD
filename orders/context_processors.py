from .models import Notification

def unread_notifications_count(request):
    """Makes the unread notification count available to all templates."""
    if request.user.is_authenticated:
        unread = Notification.objects.filter(recipient=request.user, is_read=False).order_by('-created_at')
        return {
            'unread_notifications_count': unread.count(),
            'recent_notifications': unread[:5]
        } 
    return {'unread_notifications_count': 0, 'recent_notifications': []}