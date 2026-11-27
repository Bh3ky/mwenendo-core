from django.contrib import admin


class ReadOnlyModelAdmin(admin.ModelAdmin):
    """An admin page for looking, not changing.

    Used for data the services own: a reservation changes through its
    transitions, and a ledger row is never edited at all (ADR-0011).
    """

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
