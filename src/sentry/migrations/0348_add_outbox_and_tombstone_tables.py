# Generated by Django 2.2.28 on 2022-12-29 21:05

import datetime

import django.utils.timezone
from django.db import migrations, models

import sentry.db.models.fields.bounded
import sentry.db.models.fields.jsonfield
from sentry.new_migrations.migrations import CheckedMigration


class Migration(CheckedMigration):
    # This flag is used to mark that a migration shouldn't be automatically run in production. For
    # the most part, this should only be used for operations where it's safe to run the migration
    # after your code has deployed. So this should not be used for most operations that alter the
    # schema of a table.
    # Here are some things that make sense to mark as dangerous:
    # - Large data migrations. Typically we want these to be run manually by ops so that they can
    #   be monitored and not block the deploy for a long period of time while they run.
    # - Adding indexes to large tables. Since this can take a long time, we'd generally prefer to
    #   have ops run this and not block the deploy. Note that while adding an index is a schema
    #   change, it's completely safe to run the operation after the code has deployed.
    is_dangerous = False

    dependencies = [
        ("sentry", "0347_add_project_has_minified_stack_trace_flag"),
    ]

    operations = [
        migrations.CreateModel(
            name="ControlTombstone",
            fields=[
                (
                    "id",
                    sentry.db.models.fields.bounded.BoundedBigAutoField(
                        primary_key=True, serialize=False
                    ),
                ),
                ("table_name", models.CharField(max_length=48)),
                ("object_identifier", sentry.db.models.fields.bounded.BoundedBigIntegerField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "db_table": "sentry_controltombstone",
            },
        ),
        migrations.CreateModel(
            name="RegionTombstone",
            fields=[
                (
                    "id",
                    sentry.db.models.fields.bounded.BoundedBigAutoField(
                        primary_key=True, serialize=False
                    ),
                ),
                ("table_name", models.CharField(max_length=48)),
                ("object_identifier", sentry.db.models.fields.bounded.BoundedBigIntegerField()),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
            ],
            options={
                "db_table": "sentry_regiontombstone",
            },
        ),
        migrations.CreateModel(
            name="RegionOutbox",
            fields=[
                (
                    "id",
                    sentry.db.models.fields.bounded.BoundedBigAutoField(
                        primary_key=True, serialize=False
                    ),
                ),
                ("shard_scope", sentry.db.models.fields.bounded.BoundedPositiveIntegerField()),
                ("shard_identifier", sentry.db.models.fields.bounded.BoundedBigIntegerField()),
                ("category", sentry.db.models.fields.bounded.BoundedPositiveIntegerField()),
                ("object_identifier", sentry.db.models.fields.bounded.BoundedBigIntegerField()),
                ("payload", sentry.db.models.fields.jsonfield.JSONField(null=True)),
                ("scheduled_from", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "scheduled_for",
                    models.DateTimeField(
                        default=datetime.datetime(2016, 8, 1, 0, 0, tzinfo=datetime.UTC)
                    ),
                ),
            ],
            options={
                "db_table": "sentry_regionoutbox",
                "index_together": {
                    ("shard_scope", "shard_identifier", "id"),
                    ("shard_scope", "shard_identifier", "scheduled_for"),
                    ("shard_scope", "shard_identifier", "category", "object_identifier"),
                },
            },
        ),
        migrations.CreateModel(
            name="ControlOutbox",
            fields=[
                (
                    "id",
                    sentry.db.models.fields.bounded.BoundedBigAutoField(
                        primary_key=True, serialize=False
                    ),
                ),
                ("shard_scope", sentry.db.models.fields.bounded.BoundedPositiveIntegerField()),
                ("shard_identifier", sentry.db.models.fields.bounded.BoundedBigIntegerField()),
                ("category", sentry.db.models.fields.bounded.BoundedPositiveIntegerField()),
                ("object_identifier", sentry.db.models.fields.bounded.BoundedBigIntegerField()),
                ("payload", sentry.db.models.fields.jsonfield.JSONField(null=True)),
                ("scheduled_from", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "scheduled_for",
                    models.DateTimeField(
                        default=datetime.datetime(2016, 8, 1, 0, 0, tzinfo=datetime.UTC)
                    ),
                ),
                ("region_name", models.CharField(max_length=48)),
            ],
            options={
                "db_table": "sentry_controloutbox",
                "index_together": {
                    ("region_name", "shard_scope", "shard_identifier", "id"),
                    ("region_name", "shard_scope", "shard_identifier", "scheduled_for"),
                    (
                        "region_name",
                        "shard_scope",
                        "shard_identifier",
                        "category",
                        "object_identifier",
                    ),
                },
            },
        ),
    ]
