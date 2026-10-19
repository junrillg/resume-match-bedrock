from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def populate_owner(apps, schema_editor):
    Notification = apps.get_model("matching", "CompletionNotification")
    Job = apps.get_model("matching", "Job")
    # One bounded SQL update; no source data enters the migration process.
    from django.db.models import OuterRef, Subquery
    Notification.objects.update(owner_id=Subquery(Job.objects.filter(pk=OuterRef("job_id")).values("owner_id")[:1]))


class Migration(migrations.Migration):
    dependencies = [("matching", "0006_streamevent_streamstate_and_more"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="completionnotification", name="owner", field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        migrations.RunPython(populate_owner, migrations.RunPython.noop),
        migrations.AlterField(model_name="completionnotification", name="owner", field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
        migrations.AddIndex(model_name="completionnotification", index=models.Index(fields=["owner", "-created_at", "-id"], name="notice_owner_page")),
        migrations.AddIndex(model_name="completionnotification", index=models.Index(fields=["owner", "read_at"], name="notice_owner_unread")),
    ]
