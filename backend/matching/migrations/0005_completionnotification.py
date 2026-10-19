import uuid
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("matching", "0004_document_deleted_at")]

    operations = [
        migrations.CreateModel(
            name="CompletionNotification",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("status", models.CharField(choices=[("succeeded", "Succeeded"), ("failed", "Failed")], max_length=12)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("job", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="completion_notification", to="matching.job")),
            ],
            options={
                "ordering": ["-created_at", "-id"],
                "constraints": [models.CheckConstraint(condition=models.Q(status__in=["succeeded", "failed"]), name="notification_terminal_status")],
            },
        ),
    ]
